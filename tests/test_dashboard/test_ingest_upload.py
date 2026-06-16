"""Tests for the dashboard upload size cap (E2)."""

from __future__ import annotations

import anyio

from initrunner.dashboard.routers.ingest import _save_upload_capped


class _FakeUpload:
    """Minimal async stand-in for Starlette's UploadFile."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        chunk = self._data[self._pos : self._pos + n] if n >= 0 else self._data[self._pos :]
        self._pos += len(chunk)
        return chunk


def test_save_upload_capped_rejects_oversized(tmp_path):
    """Regression (E2): an upload over the limit is refused without being fully
    buffered, and the partial file is removed."""
    dest = tmp_path / "big.bin"
    ok = anyio.run(_save_upload_capped, _FakeUpload(b"x" * 5000), dest, 1000)
    assert ok is False
    assert not dest.exists()


def test_save_upload_capped_accepts_within_limit(tmp_path):
    dest = tmp_path / "ok.bin"
    ok = anyio.run(_save_upload_capped, _FakeUpload(b"hello world"), dest, 1000)
    assert ok is True
    assert dest.read_bytes() == b"hello world"
