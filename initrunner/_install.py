"""How this copy of InitRunner was installed, and how to add an extra to it.

Every command that hits a missing optional dependency needs the same two
answers: what command would install it here, and is it safe to run that command
without the user watching.  Both are derived from the install's own records --
uv's ``uv-receipt.toml``, pipx's ``pipx_metadata.json``, pip's
``direct_url.json`` -- rather than a state file of our own, so a copy installed
before this module existed is still understood.

The bar for running an installer automatically is deliberately high.  ``uv tool
install`` and ``pipx install`` re-resolve the whole tool environment from the
spec they are given, so passing one extra silently uninstalls every other extra
the user had.  Anything this module cannot reconstruct exactly -- a pipx venv, a
tool installed from a directory or a git URL, a receipt carrying ``--with``
packages, Windows (where the running ``.exe`` cannot be replaced) -- returns
``None`` from :func:`install_command` and gets a printed command instead.

Stdlib only: this is imported from ``_compat`` and the telemetry path, both of
which run on a core install.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Install methods.  The first four are recorded by the installer that made them;
# the rest are inferred.
UV_TOOL = "uv-tool"
PIPX = "pipx"
EDITABLE = "editable"
DOCKER = "docker"
UVX = "uvx"
UV_PIP = "uv-pip"
PIP = "pip"
UNKNOWN = "unknown"

# Set on the process we re-exec into, so the second run does not offer to
# install again if the first install did not actually resolve the problem.
REEXEC_ENV_VAR = "INITRUNNER_REEXEC"

# A requirement string as far as we need to read one: name, optional extras,
# optional version specifier.  ``fullmatch`` only -- a prefix match would read
# "initrunner[recommended]==2026.8.10" as an unpinned "initrunner[recommended]"
# and quietly drop the pin when rebuilding the command.
_REQUIREMENT_RE = re.compile(
    r"initrunner(?:\[(?P<extras>[^\]]*)\])?(?P<specifier>[<>=!~].*)?",
    re.IGNORECASE,
)

# Receipt requirement keys we know how to rebuild.  Anything else (a directory
# or git source, a marker, a key added by a future uv) means hands off.
_KNOWN_RECEIPT_KEYS = {"name", "extras", "specifier"}

_reexeced = False


# ---------------------------------------------------------------------------
# Re-exec loop guard
# ---------------------------------------------------------------------------


def consume_reexec_flag() -> bool:
    """Read and remove the re-exec marker from the environment.

    Called once at CLI entry, before any command runs.  Removing it here keeps
    it from being inherited by daemons, service ticks and MCP servers, which are
    spawned with the parent's environment and would otherwise never offer to
    install anything for the rest of their lives.
    """
    global _reexeced
    _reexeced = os.environ.pop(REEXEC_ENV_VAR, None) is not None
    return _reexeced


def was_reexeced() -> bool:
    """True when this process is the re-exec of a command that just installed."""
    return _reexeced


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _in_container() -> bool:
    if os.environ.get("INITRUNNER_IN_DOCKER"):
        return True
    # Podman writes /run/.containerenv where Docker writes /.dockerenv.
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _is_editable() -> bool:
    try:
        import importlib.metadata as md

        raw = md.distribution("initrunner").read_text("direct_url.json")
    except Exception:
        return False
    if not raw:
        return False
    import json

    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except Exception:
        return False


def install_method() -> str:
    """Best-effort name for how this copy was installed.  Never raises."""
    try:
        if _in_container():
            return DOCKER
        if _is_editable():
            return EDITABLE
        prefix = Path(sys.prefix)
        # UV_TOOL_DIR and PIPX_HOME move these trees, so look for the receipt
        # each installer leaves rather than for a path substring.
        if (prefix / "uv-receipt.toml").exists():
            return UV_TOOL
        if (prefix / "pipx_metadata.json").exists():
            return PIPX
        # `uvx initrunner` / `uv tool run` builds a throwaway env in uv's cache.
        if "/archive-v0/" in prefix.as_posix():
            return UVX
        if shutil.which("uv"):
            return UV_PIP
        import importlib.util

        if importlib.util.find_spec("pip") is not None:
            return PIP
    except Exception:
        return UNKNOWN
    return UNKNOWN


# ---------------------------------------------------------------------------
# Reading what is already installed
# ---------------------------------------------------------------------------


def _parse_requirement(text: str) -> tuple[set[str], str] | None:
    """Split an ``initrunner[a,b]==1.2`` spec into extras and specifier.

    ``None`` when the string is not a plain requirement on initrunner itself
    (a URL, a path, a different package).
    """
    match = _REQUIREMENT_RE.fullmatch(text.strip())
    if match is None:
        return None
    raw_extras = match.group("extras") or ""
    extras = {e.strip() for e in raw_extras.split(",") if e.strip()}
    return extras, (match.group("specifier") or "").strip()


def _uv_receipt() -> dict | None:
    try:
        import tomllib

        return tomllib.loads((Path(sys.prefix) / "uv-receipt.toml").read_text(encoding="utf-8"))
    except Exception:
        return None


def _uv_tool_spec() -> tuple[set[str], str, str | None] | None:
    """``(extras, specifier, python)`` from the uv receipt, or ``None``.

    ``None`` means the receipt describes something this module will not rebuild:
    more than one requirement (``uv tool install --with``), a non-registry
    source, or a key it does not recognise.  Reconstructing those from the name
    alone would swap a directory install for a PyPI one or drop a second
    package's entry points.
    """
    receipt = _uv_receipt()
    if not receipt:
        return None
    tool = receipt.get("tool")
    if not isinstance(tool, dict):
        return None
    requirements = tool.get("requirements")
    if not isinstance(requirements, list) or len(requirements) != 1:
        return None
    req = requirements[0]
    if not isinstance(req, dict) or req.get("name") != "initrunner":
        return None
    if not set(req) <= _KNOWN_RECEIPT_KEYS:
        return None
    extras = req.get("extras") or []
    if not isinstance(extras, list) or not all(isinstance(e, str) for e in extras):
        return None
    specifier = req.get("specifier") or ""
    if not isinstance(specifier, str):
        return None
    python = tool.get("python")
    return set(extras), specifier, python if isinstance(python, str) else None


def _pipx_spec() -> tuple[set[str], str] | None:
    """``(extras, specifier)`` from pipx metadata, or ``None`` when unreadable."""
    try:
        import json

        raw = json.loads((Path(sys.prefix) / "pipx_metadata.json").read_text(encoding="utf-8"))
        package_or_url = raw["main_package"]["package_or_url"]
    except Exception:
        return None
    if not isinstance(package_or_url, str):
        return None
    return _parse_requirement(package_or_url)


def current_extras() -> set[str]:
    """Extras this install was created with, as far as its records show.

    Empty when there is no record to read; callers that rebuild a whole
    environment must treat that as "cannot rebuild", not as "no extras".
    """
    method = install_method()
    if method == UV_TOOL:
        spec = _uv_tool_spec()
        return set(spec[0]) if spec else set()
    if method == PIPX:
        spec = _pipx_spec()
        return set(spec[0]) if spec else set()
    return set()


# ---------------------------------------------------------------------------
# Building the command
# ---------------------------------------------------------------------------


def _spec(extras: Iterable[str], specifier: str = "") -> str:
    names = sorted({e for e in extras if e})
    joined = ",".join(names)
    return f"initrunner[{joined}]{specifier}" if joined else f"initrunner{specifier}"


def install_command(extras: Iterable[str]) -> list[str] | None:
    """The command that adds *extras* to this install, or ``None``.

    ``None`` means "do not run anything automatically"; :func:`manual_hint` has
    something for the user to run instead.  Every returned command is safe to
    run unattended: it either adds to the environment (pip, uv pip) or rebuilds
    it from a spec that already carries the extras the user had.
    """
    wanted = {e for e in extras if e}
    if not wanted:
        return None
    method = install_method()

    # Replacing the running initrunner.exe fails on Windows; uv and pipx both
    # rewrite the launcher, so those two are print-only there.
    if sys.platform == "win32" and method in (UV_TOOL, PIPX):
        return None

    if method == UV_TOOL:
        spec = _uv_tool_spec()
        if spec is None:
            return None
        have, specifier, python = spec
        # Keep a pin the user chose (installer --version); never add one, since
        # a specifier in the receipt is what `uv tool upgrade` respects.
        cmd = ["uv", "tool", "install", _spec(have | wanted, specifier)]
        if python:
            cmd += ["--python", python]
        # No --force: uv replaces the environment when the requirement changes,
        # and --force additionally recreates it from scratch.
        return cmd

    if method == UV_PIP:
        # Without --python this resolves $VIRTUAL_ENV or ./.venv, which may not
        # be the interpreter that is about to import the package.
        return ["uv", "pip", "install", "--python", sys.executable, _spec(wanted)]

    if method == PIP:
        return [sys.executable, "-m", "pip", "install", _spec(wanted)]

    # pipx, editable checkouts, uvx, containers and unknown installs print.
    return None


def manual_hint(extras: Iterable[str]) -> str:
    """A command the user can run to add *extras*, for any install method."""
    wanted = {e for e in extras if e}
    cmd = install_command(wanted)
    if cmd is not None:
        return shlex.join(cmd)

    method = install_method()

    if method == UV_TOOL:
        spec = _uv_tool_spec()
        if spec is not None:
            have, specifier, _python = spec
            return shlex.join(["uv", "tool", "install", _spec(have | wanted, specifier)])
        have = current_extras()
        return (
            shlex.join(["uv", "tool", "install", _spec(have | wanted)])
            + "  (re-add any --with packages your install had)"
        )

    if method == PIPX:
        spec = _pipx_spec()
        if spec is not None:
            have, specifier = spec
            return shlex.join(["pipx", "install", "--force", _spec(have | wanted, specifier)])
        return (
            shlex.join(["pipx", "install", "--force", _spec(wanted)])
            + "  (add the extras you already had; pipx rebuilds from this spec)"
        )

    if method == EDITABLE:
        return shlex.join(["uv", "sync", *[arg for e in sorted(wanted) for arg in ("--extra", e)]])

    if method == UVX:
        return shlex.join(["uvx", "--from", _spec(wanted), "initrunner"]) + " ..."

    if method == DOCKER:
        return (
            f"use the initrunner:latest image, or rebuild with "
            f"--build-arg EXTRAS={','.join(sorted(wanted))}"
        )

    return shlex.join([sys.executable, "-m", "pip", "install", _spec(wanted)])
