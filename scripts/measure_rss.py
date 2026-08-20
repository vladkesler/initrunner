#!/usr/bin/env python3
"""Measure InitRunner's memory footprint and print the tables docs publish.

Every scenario runs in a fresh interpreter and reports ``VmRSS`` from
``/proc/self/status``, so nothing an earlier scenario imported can leak into
the next one. Scenarios that need an optional dependency are skipped when it
is not installed, which is how the same script produces both the core and the
full-install numbers.

Usage:
    python scripts/measure_rss.py                # median of 3
    python scripts/measure_rss.py --repeat 5
    python scripts/measure_rss.py --agents 1,5,50

Linux only (VmRSS). Not a CI gate: allocators and platforms move these numbers
around, and a threshold that fails on someone's laptop teaches people to
ignore it. The regression gate is tests/test_core_footprint.py, which asserts
on module names instead.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLE = REPO_ROOT / "examples" / "roles" / "hello-world.yaml"

PREAMBLE = """
import json, os, re, sys
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")
os.environ.setdefault("INITRUNNER_TELEMETRY", "0")
os.environ.setdefault("INITRUNNER_NO_TELEMETRY_PROMPT", "1")

def _report():
    rss_kb = int(re.search(r"VmRSS:\\s+(\\d+)", open("/proc/self/status").read()).group(1))
    print("@@" + json.dumps({"rss": round(rss_kb / 1024), "modules": len(sys.modules)}))
"""

# (label, note, code, required module or None)
LAYERS: list[tuple[str, str, str, str | None]] = [
    (
        "Bare CPython interpreter",
        "",
        "pass",
        None,
    ),
    (
        "+ Pydantic",
        "pydantic-core is a compiled Rust extension",
        "import pydantic",
        None,
    ),
    (
        "+ PydanticAI",
        "the agent framework itself",
        "import pydantic, pydantic_ai",
        None,
    ),
    (
        "+ OpenAI SDK",
        "only the SDK for the configured provider loads",
        "import pydantic_ai; from pydantic_ai.models.openai import OpenAIChatModel",
        None,
    ),
    (
        "+ InitRunner",
        "schema, executor, CLI and every built-in tool",
        "from pydantic_ai.models.openai import OpenAIChatModel\n"
        "import initrunner.agent.executor\n"
        "from initrunner.agent.tools._registry import get_tool_types\n"
        "get_tool_types()",
        None,
    ),
    (
        "+ MCP stack (`mcp` extra)",
        "pydantic_ai imports it eagerly whenever fastmcp is installed",
        "import fastmcp.client\n"
        "from pydantic_ai.models.openai import OpenAIChatModel\n"
        "import initrunner.agent.executor\n"
        "from initrunner.agent.tools._registry import get_tool_types\n"
        "get_tool_types()",
        "fastmcp",
    ),
    (
        "+ LanceDB (`vector` extra)",
        "only when the role configures ingestion or vector memory",
        "from pydantic_ai.models.openai import OpenAIChatModel\n"
        "import initrunner.agent.executor\n"
        "import lancedb",
        "lancedb",
    ),
]

PACKED = """
from pathlib import Path
from initrunner.agent.loader import load_and_build
from initrunner.agent.schema.security import SecurityPolicy
from initrunner.server.app import ServedMember, create_multi_app

members = {{}}
for i in range({n}):
    role, agent = load_and_build(Path({role!r}), model_override="openai:gpt-4o-mini")
    members[f"agent-{{i}}"] = ServedMember(key=f"agent-{{i}}", role=role, agent=agent)
create_multi_app(members, security=SecurityPolicy())
"""


def measure(code: str, *, repeat: int, block_mcp: bool = False) -> dict:
    """Run *code* in a fresh interpreter *repeat* times, return the median."""
    prelude = 'import sys; sys.modules["fastmcp"] = None\n' if block_mcp else ""
    source = PREAMBLE + prelude + code + "\n_report()\n"
    samples = []
    for _ in range(repeat):
        proc = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=300,
        )
        if proc.returncode != 0:
            raise SystemExit(f"scenario failed:\n{proc.stderr}")
        line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("@@"))
        samples.append(json.loads(line[2:]))
    return {
        "rss": round(statistics.median(s["rss"] for s in samples)),
        "modules": round(statistics.median(s["modules"] for s in samples)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="samples per scenario (median wins)")
    parser.add_argument("--agents", default="1,5,50", help="packed-agent counts to measure")
    args = parser.parse_args()

    if platform.system() != "Linux":
        raise SystemExit("VmRSS is Linux-only; run this in the container or on a Linux host.")

    has_mcp = find_spec("fastmcp") is not None
    has_vector = find_spec("lancedb") is not None

    print(f"# CPython {platform.python_version()} on {platform.machine()}")
    print(f"# mcp extra: {'installed' if has_mcp else 'absent'}", end="  ")
    print(f"vector extra: {'installed' if has_vector else 'absent'}")
    print(f"# median of {args.repeat} runs\n")

    print("| Layer | RSS | Modules | Notes |")
    print("|---|---|---|---|")
    previous = 0
    for label, note, code, needs in LAYERS:
        if needs is not None and find_spec(needs) is None:
            print(f"| {label} | not installed | | {note} |")
            continue
        # Layer rows are cumulative except the two optional extras, which are
        # add-ons to the InitRunner row rather than steps in one chain.
        result = measure(code, repeat=args.repeat, block_mcp=has_mcp and needs != "fastmcp")
        delta = result["rss"] - previous if previous else result["rss"]
        shown = f"{result['rss']} MB" if not previous else f"+{delta} MB"
        print(f"| {label} | {shown} | {result['modules']} | {note} |")
        if needs is None:
            previous = result["rss"]

    print("\n| Agents in one process | RSS (core) | RSS (with `mcp`) |")
    print("|---|---|---|")
    for n in [int(x) for x in args.agents.split(",")]:
        code = PACKED.format(n=n, role=str(ROLE))
        lean = measure(code, repeat=args.repeat, block_mcp=True)
        if has_mcp:
            full = f"{measure(code, repeat=args.repeat)['rss']} MB"
        else:
            full = "not installed"
        print(f"| {n} | {lean['rss']} MB | {full} |")


if __name__ == "__main__":
    main()
