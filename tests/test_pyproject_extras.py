"""What the extras table promises has to match what pyproject actually ships.

The docs advertise four things: a core install, ``[recommended]``, ``[all]``,
and the provider names. Everything else stays in ``pyproject.toml`` for
packagers and for ``doctor --fix``. These tests are what stops that split from
rotting: the old table drifted to the point of describing an extra that included
Slack as "Telegram and Discord" and calling ``all`` "every extra below" when it
was not.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DOC = ROOT / "docs" / "getting-started" / "installation.md"

# Extras a human should never have to learn. They stay defined so packagers can
# pin one, and so `doctor --fix` and the install prompt have a name to install.
PACKAGER_ONLY = {
    "a2a",
    "audio",
    "channels",
    "dashboard",
    "desktop",
    "discord",
    "ingest",
    "local-embeddings",
    "mcp",
    "observability",
    "safety",
    "search",
    "slack",
    "telegram",
    "vault",
    "vault-keyring",
    "vector",
}

# `all` leaves these out on purpose, so "everything" stays a sane download.
NOT_IN_ALL = {
    "desktop",  # pywebview wants a system GUI toolkit
    "local-embeddings",  # fastembed pulls in the ONNX runtime
    "recommended",  # a subset of all
    "all",
}

_REQUIREMENT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([^\]]*)\])?")


@pytest.fixture(scope="module")
def extras() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def _split(requirement: str) -> tuple[str, set[str]]:
    """``pydantic-ai-slim[google]>=2`` becomes ``("pydantic-ai-slim", {"google"})``."""
    match = _REQUIREMENT.match(requirement.strip())
    assert match, requirement
    name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
    return name, {e.strip() for e in (match.group(2) or "").split(",") if e.strip()}


def _self_references(requirements: list[str]) -> set[str]:
    """The ``initrunner[x]`` entries in one extra's requirement list."""
    found: set[str] = set()
    for req in requirements:
        match = re.fullmatch(r"initrunner\[([^\]]+)\]", req.strip())
        if match:
            found.update(part.strip() for part in match.group(1).split(","))
    return found


def _flatten(name: str, extras: dict[str, list[str]], seen: set[str] | None = None) -> set[str]:
    """Every extra *name* pulls in, directly or through another extra."""
    seen = seen if seen is not None else set()
    for referenced in _self_references(extras.get(name, [])):
        if referenced in seen:
            continue
        seen.add(referenced)
        _flatten(referenced, extras, seen)
    return seen


def _packages(name: str, extras: dict[str, list[str]]) -> dict[str, set[str]]:
    """Distribution name to the extras of it that *name* installs.

    Merged per distribution, because `all` asks for
    ``pydantic-ai-slim[anthropic,google,...]`` in one line where the `google`
    extra asks for ``pydantic-ai-slim[google]``. Comparing the strings would
    call those different; comparing what they install does not.
    """
    installs: dict[str, set[str]] = {}
    for extra in {name} | _flatten(name, extras):
        for req in extras.get(extra, []):
            if req.strip().startswith("initrunner["):
                continue
            dist, dist_extras = _split(req)
            installs.setdefault(dist, set()).update(dist_extras)
    return installs


def test_every_extra_is_documented_or_deliberately_not(extras):
    """A new extra has to reach the docs table or the PACKAGER_ONLY list."""
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    undocumented = {
        name
        for name in extras
        if name not in PACKAGER_ONLY and f"initrunner[{name}]" not in doc and f"`{name}`" not in doc
    }
    assert not undocumented, (
        f"extras missing from {INSTALL_DOC.name}: {sorted(undocumented)}. "
        "Add them to the table, or to PACKAGER_ONLY if humans should not see them."
    )


def test_packager_only_names_are_real_extras(extras):
    """The list above must not outlive the extras it names."""
    assert PACKAGER_ONLY <= set(extras)


def test_all_covers_everything_it_should(extras):
    """Installing `[all]` gives you at least what any other extra would."""
    everything = _packages("all", extras)
    for name in set(extras) - NOT_IN_ALL:
        for dist, wanted in _packages(name, extras).items():
            assert dist in everything, f"[all] does not cover [{name}]: missing {dist}"
            assert wanted <= everything[dist], (
                f"[all] has {dist} but not its {sorted(wanted - everything[dist])} "
                f"extras, which [{name}] needs"
            )


def test_all_excludes_only_what_the_docs_say(extras):
    """If something stays outside `[all]`, the installation page has to say so."""
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    for name in NOT_IN_ALL - {"recommended", "all"}:
        assert name in doc, f"{name} is outside [all] but the docs do not explain it"


def test_every_provider_has_its_own_extra(extras):
    """`initrunner[<provider>]` should work for any provider a role can name."""
    from initrunner._compat import _PROVIDER_EXTRAS

    for provider, extra in _PROVIDER_EXTRAS.items():
        assert extra in extras, f"provider {provider} maps to unknown extra {extra}"


def test_recommended_is_what_the_docs_claim(extras):
    """The installer default, spelled out in one place."""
    assert _flatten("recommended", extras) == {
        "search",
        "ingest",
        "dashboard",
        "mcp",
        "vector",
    }


INSTALL_COMMAND = re.compile(r"(pip install|uv add|pipx install|uv sync --extra)")

# Operator and contributor pages, where naming one extra is the point:
# memory-footprint measures them one at a time, CI docs sync a checkout, and
# the installation and doctor pages document the mechanism itself.
_EXEMPT_DOCS = {
    "docs/core/ingestion.md",
    "docs/getting-started/installation.md",
    "docs/getting-started/installer.md",
    "docs/operations/cicd.md",
    "docs/operations/doctor.md",
    "docs/operations/memory-footprint.md",
    "docs/operations/pypi_publish.md",
    "docs/operations/testing.md",
}


def test_no_doc_tells_a_user_to_install_a_fine_grained_extra():
    """Feature pages point at bundles and at the prompt, not at install lines.

    Naming an extra in prose is fine, and so is quoting InitRunner's own error
    output. What must not appear is a command telling someone to install one by
    hand, because that is the advice this change exists to stop giving.
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "docs").rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in _EXEMPT_DOCS:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not INSTALL_COMMAND.search(line):
                continue
            named = set(re.findall(r"uv sync --extra ([a-z0-9-]+)", line))
            for group in re.findall(r"initrunner\[([a-z0-9,-]+)\]", line):
                named.update(group.split(","))
            if named & PACKAGER_ONLY:
                offenders.append(f"{rel}:{line_no}: {line.strip()}")
    assert not offenders, "hand-install commands for fine-grained extras:\n" + "\n".join(offenders)
