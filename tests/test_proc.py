"""Reading resident memory from /proc."""

from __future__ import annotations

import os

import pytest

from initrunner._proc import current_rss_mb, process_rss_mb

_LINUX = os.path.exists("/proc/self/status")


@pytest.mark.skipif(not _LINUX, reason="VmRSS is Linux-only")
class TestProcessRssMb:
    def test_reads_this_process(self):
        rss = process_rss_mb()
        assert rss is not None
        assert rss > 0

    def test_current_rss_matches_self(self):
        assert current_rss_mb() is not None

    def test_reads_another_pid(self):
        assert process_rss_mb(os.getpid()) == pytest.approx(process_rss_mb(), abs=2)

    def test_missing_process_returns_none(self):
        """A PID that has exited is a "no number to show", not an error."""
        assert process_rss_mb(2**30) is None


def test_unreadable_proc_returns_none(monkeypatch):
    """Covers non-Linux platforms, where /proc does not exist at all."""

    def _no_proc(*args, **kwargs):
        raise OSError("no /proc here")

    monkeypatch.setattr("builtins.open", _no_proc)
    assert process_rss_mb() is None


def test_status_without_vmrss_returns_none(monkeypatch, tmp_path):
    """Some kernels omit VmRSS; report nothing rather than guessing."""
    fake = tmp_path / "status"
    fake.write_text("Name:\tpython\nVmSize:\t 123 kB\n")
    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda path, *a, **kw: (
            real_open(fake, *a, **kw)
            if str(path).startswith("/proc/")
            else real_open(path, *a, **kw)
        ),
    )
    assert process_rss_mb() is None
