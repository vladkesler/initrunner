"""Reading a process's own resident memory, without a dependency.

Container limits and cloud bills are denominated in RSS, so the number worth
reporting is the one the kernel reports, not a sum of what we think we
allocated. ``/proc/<pid>/status`` has it on Linux and nowhere else, which is
also where InitRunner supervises long-running processes.
"""

from __future__ import annotations

import os
import re

_VMRSS_RE = re.compile(r"^VmRSS:\s+(\d+)\s+kB", re.MULTILINE)


def process_rss_mb(pid: int | None = None) -> int | None:
    """Resident set size of *pid* (default: this process) in whole MB.

    Returns ``None`` when it cannot be read: a non-Linux platform, a process
    that has since exited, or a kernel that does not report ``VmRSS``. Callers
    treat that as "no number to show", never as an error.
    """
    target = "self" if pid is None else str(pid)
    try:
        with open(f"/proc/{target}/status") as fh:
            content = fh.read()
    except OSError:
        return None

    match = _VMRSS_RE.search(content)
    if match is None:
        return None
    return round(int(match.group(1)) / 1024)


def current_rss_mb() -> int | None:
    """Resident set size of the running process in whole MB."""
    return process_rss_mb(os.getpid())
