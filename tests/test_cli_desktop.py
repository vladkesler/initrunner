"""Tests for ``initrunner desktop``."""

from __future__ import annotations

import builtins
import json
import sys
from http.client import HTTPResponse
from unittest import mock

import pytest

from initrunner.cli.desktop_cmd import (
    _ensure_gi,
    _find_base_executable,
    _is_dashboard_healthy,
)

# -- health probe -----------------------------------------------------------


def test_healthy_probe():
    body = json.dumps({"status": "ok"}).encode()
    resp = mock.Mock(spec=HTTPResponse, status=200)
    resp.read.return_value = body
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=resp):
        assert _is_dashboard_healthy(8100) is True


def test_unhealthy_probe_wrong_status():
    resp = mock.Mock(spec=HTTPResponse, status=500)
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=resp):
        assert _is_dashboard_healthy(8100) is False


def test_unhealthy_probe_connection_refused():
    with mock.patch("urllib.request.urlopen", side_effect=ConnectionError):
        assert _is_dashboard_healthy(8100) is False


# -- CLI command -------------------------------------------------------------

_WEBVIEW_MOD = "initrunner.cli.desktop_cmd"


def _mock_webview_modules():
    """Return a dict of mock webview modules for sys.modules patching."""
    wv = mock.MagicMock()
    wv.create_window = mock.MagicMock()
    wv.start = mock.MagicMock()
    wv_util = mock.MagicMock()
    wv_util.WebViewException = type("WebViewException", (Exception,), {})
    return {"webview": wv, "webview.util": wv_util}


def test_missing_pywebview():
    real_import = builtins.__import__

    def _block_webview(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("No module named 'webview'")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_block_webview):
        from initrunner.cli.desktop_cmd import desktop

        with pytest.raises(SystemExit):
            desktop(port=8100)


def test_reuse_existing_backend():
    wv_mods = _mock_webview_modules()
    with (
        mock.patch.dict("sys.modules", wv_mods),
        mock.patch(f"{_WEBVIEW_MOD}._is_dashboard_healthy", return_value=True),
        mock.patch(f"{_WEBVIEW_MOD}._ensure_gi"),
    ):
        from initrunner.cli.desktop_cmd import desktop

        desktop(port=8100)
        wv_mods["webview"].create_window.assert_called_once()
        wv_mods["webview"].start.assert_called_once()


def test_port_conflict():
    """Port occupied by non-dashboard process -> clean exit."""
    wv_mods = _mock_webview_modules()

    with (
        mock.patch.dict("sys.modules", wv_mods),
        mock.patch(f"{_WEBVIEW_MOD}._is_dashboard_healthy", return_value=False),
        mock.patch(f"{_WEBVIEW_MOD}._ensure_gi"),
        mock.patch("socket.socket") as mock_sock_cls,
    ):
        sock_inst = mock_sock_cls.return_value
        sock_inst.bind.side_effect = OSError("Address already in use")

        from initrunner.cli.desktop_cmd import desktop

        with pytest.raises(SystemExit):
            desktop(port=8100)


def test_worker_failure():
    """Server thread failure is captured via queue, not silent timeout."""
    wv_mods = _mock_webview_modules()

    mock_server = mock.MagicMock()
    mock_server.run.side_effect = SystemExit(1)

    mock_uvicorn = mock.MagicMock()
    mock_uvicorn.Config.return_value = mock.MagicMock()
    mock_uvicorn.Server.return_value = mock_server

    with (
        mock.patch.dict(
            "sys.modules",
            {**wv_mods, "uvicorn": mock_uvicorn},
        ),
        mock.patch(f"{_WEBVIEW_MOD}._is_dashboard_healthy", return_value=False),
        mock.patch(f"{_WEBVIEW_MOD}._ensure_gi"),
        mock.patch("socket.socket") as mock_sock_cls,
        mock.patch("initrunner.dashboard.app.create_app", return_value=mock.MagicMock()),
        mock.patch("initrunner.dashboard.config.DashboardSettings", return_value=mock.MagicMock()),
    ):
        sock_inst = mock_sock_cls.return_value
        sock_inst.bind = mock.MagicMock()

        from initrunner.cli.desktop_cmd import desktop

        with pytest.raises(SystemExit):
            desktop(port=8100)


# -- Linux renderer detection ------------------------------------------------


def test_linux_missing_renderer(monkeypatch):
    """On Linux, missing GTK renderer prints distro-specific install hint."""
    from initrunner.cli.desktop_cmd import _handle_webview_error

    monkeypatch.setattr("sys.platform", "linux")

    exc = Exception("GTK runtime not found")
    ubuntu_release = 'NAME="Ubuntu"\nID=ubuntu\n'
    with mock.patch("builtins.open", mock.mock_open(read_data=ubuntu_release)):
        with pytest.raises(SystemExit):
            _handle_webview_error(exc)


def test_non_linux_renderer_error_reraises(monkeypatch):
    """On non-Linux, WebViewException is re-raised, not swallowed."""
    from initrunner.cli.desktop_cmd import _handle_webview_error

    monkeypatch.setattr("sys.platform", "darwin")

    exc = Exception("GTK runtime not found")
    with pytest.raises(Exception, match="GTK runtime not found"):
        _handle_webview_error(exc)


# -- _ensure_gi bridge -------------------------------------------------------


class TestEnsureGi:
    """Tests for the system GI bridge."""

    def test_gi_already_importable(self, monkeypatch):
        """No subprocess call when gi is already available."""
        gi_mock = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"gi": gi_mock}):
            # Should return without touching subprocess.
            with mock.patch("subprocess.run") as run_mock:
                _ensure_gi()
                run_mock.assert_not_called()

    def test_noop_on_non_linux(self, monkeypatch):
        """_ensure_gi is a no-op on non-Linux platforms."""
        monkeypatch.setattr("sys.platform", "darwin")
        # gi is not importable:
        real_import = builtins.__import__

        def _block_gi(name, *args, **kwargs):
            if name == "gi":
                raise ImportError
            return real_import(name, *args, **kwargs)

        with (
            mock.patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "gi"}),
            mock.patch("builtins.__import__", side_effect=_block_gi),
        ):
            # Should return without error on non-Linux.
            _ensure_gi()

    def test_bridge_success(self, monkeypatch, tmp_path):
        """Probe finds system gi, imports it, then removes site dir from sys.path."""
        monkeypatch.setattr("sys.platform", "linux")
        site_dir = str(tmp_path / "lib" / "python3" / "dist-packages")

        # gi is not in sys.modules initially.
        real_import = builtins.__import__
        call_count = 0

        def _import_gi(name, *args, **kwargs):
            nonlocal call_count
            if name == "gi":
                call_count += 1
                if call_count == 1:
                    raise ImportError  # first attempt fails
                return mock.MagicMock()  # second attempt (after path injection) succeeds
            return real_import(name, *args, **kwargs)

        probe_result = mock.Mock()
        probe_result.returncode = 0
        probe_result.stdout = site_dir + "\n"

        with (
            mock.patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "gi"}),
            mock.patch("builtins.__import__", side_effect=_import_gi),
            mock.patch("subprocess.run", return_value=probe_result),
            mock.patch(f"{_WEBVIEW_MOD}._find_base_executable", return_value="/usr/bin/python3.12"),
        ):
            original_path = sys.path.copy()
            _ensure_gi()
            # Path must be cleaned up after import to avoid polluting
            # the venv with stale system packages (e.g. typing_extensions).
            assert site_dir not in sys.path
            sys.path[:] = original_path

    def test_bridge_abi_mismatch(self, monkeypatch, tmp_path):
        """Probe succeeds but retry import fails -> ABI mismatch message."""
        monkeypatch.setattr("sys.platform", "linux")
        site_dir = str(tmp_path / "lib" / "python3" / "dist-packages")

        real_import = builtins.__import__

        def _always_fail_gi(name, *args, **kwargs):
            if name == "gi":
                raise ImportError
            return real_import(name, *args, **kwargs)

        probe_result = mock.Mock()
        probe_result.returncode = 0
        probe_result.stdout = site_dir + "\n"

        with (
            mock.patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "gi"}),
            mock.patch("builtins.__import__", side_effect=_always_fail_gi),
            mock.patch("subprocess.run", return_value=probe_result),
            mock.patch(f"{_WEBVIEW_MOD}._find_base_executable", return_value="/usr/bin/python3.12"),
        ):
            original_path = sys.path.copy()
            with pytest.raises(SystemExit):
                _ensure_gi()
            sys.path[:] = original_path

    def test_bridge_probe_fails(self, monkeypatch):
        """Probe subprocess fails -> exits with install hint."""
        monkeypatch.setattr("sys.platform", "linux")

        real_import = builtins.__import__

        def _block_gi(name, *args, **kwargs):
            if name == "gi":
                raise ImportError
            return real_import(name, *args, **kwargs)

        probe_result = mock.Mock()
        probe_result.returncode = 1
        probe_result.stdout = ""

        ubuntu_release = 'NAME="Ubuntu"\nID=ubuntu\n'
        with (
            mock.patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "gi"}),
            mock.patch("builtins.__import__", side_effect=_block_gi),
            mock.patch("subprocess.run", return_value=probe_result),
            mock.patch(f"{_WEBVIEW_MOD}._find_base_executable", return_value="/usr/bin/python3.12"),
            mock.patch("builtins.open", mock.mock_open(read_data=ubuntu_release)),
        ):
            with pytest.raises(SystemExit):
                _ensure_gi()

    def test_bridge_no_base_executable(self, monkeypatch):
        """No base executable found -> exits with install hint."""
        monkeypatch.setattr("sys.platform", "linux")

        real_import = builtins.__import__

        def _block_gi(name, *args, **kwargs):
            if name == "gi":
                raise ImportError
            return real_import(name, *args, **kwargs)

        ubuntu_release = 'NAME="Ubuntu"\nID=ubuntu\n'
        with (
            mock.patch.dict("sys.modules", {k: v for k, v in sys.modules.items() if k != "gi"}),
            mock.patch("builtins.__import__", side_effect=_block_gi),
            mock.patch(f"{_WEBVIEW_MOD}._find_base_executable", return_value=None),
            mock.patch("builtins.open", mock.mock_open(read_data=ubuntu_release)),
        ):
            with pytest.raises(SystemExit):
                _ensure_gi()


# -- _find_base_executable ---------------------------------------------------


class TestFindBaseExecutable:
    """Tests for the base interpreter fallback chain."""

    def test_uses_base_executable(self, monkeypatch, tmp_path):
        """Prefers sys._base_executable when it exists."""
        fake_exe = tmp_path / "python3.12"
        fake_exe.touch()
        monkeypatch.setattr(sys, "_base_executable", str(fake_exe))

        assert _find_base_executable() == str(fake_exe)

    def test_falls_back_to_base_prefix(self, monkeypatch, tmp_path):
        """Falls back to base_prefix/bin/pythonX.Y."""
        monkeypatch.delattr(sys, "_base_executable", raising=False)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        fake_exe = bin_dir / f"python{ver}"
        fake_exe.touch()
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path))

        assert _find_base_executable() == str(fake_exe)

    def test_falls_back_to_shutil_which(self, monkeypatch, tmp_path):
        """Falls back to shutil.which('python3') as last resort."""
        monkeypatch.delattr(sys, "_base_executable", raising=False)
        # base_prefix candidate doesn't exist.
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "nonexistent"))

        with mock.patch("shutil.which", return_value="/usr/bin/python3"):
            assert _find_base_executable() == "/usr/bin/python3"

    def test_returns_none_when_nothing_found(self, monkeypatch, tmp_path):
        """Returns None when no interpreter can be found."""
        monkeypatch.delattr(sys, "_base_executable", raising=False)
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "nonexistent"))

        with mock.patch("shutil.which", return_value=None):
            assert _find_base_executable() is None

    def test_skips_nonexistent_base_executable(self, monkeypatch, tmp_path):
        """Skips _base_executable if the path doesn't exist on disk."""
        monkeypatch.setattr(sys, "_base_executable", "/no/such/python")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        fake_exe = bin_dir / f"python{ver}"
        fake_exe.touch()
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path))

        assert _find_base_executable() == str(fake_exe)
