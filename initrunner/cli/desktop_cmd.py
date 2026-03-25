"""``initrunner desktop`` -- launch the dashboard in a native window."""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

_HEALTH_TIMEOUT = 30.0
_HEALTH_INTERVAL = 0.25


def desktop(
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8100,
    roles_dir: Annotated[
        list[Path] | None,
        typer.Option("--roles-dir", help="Extra directories to scan for roles"),
    ] = None,
) -> None:
    """Launch the dashboard in a native desktop window."""
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        console.print(
            "[red]Desktop mode requires pywebview.[/red]\n"
            "Install with: [bold]pip install 'initrunner\\[desktop]'[/bold]"
        )
        raise SystemExit(1) from None

    _ensure_gi()

    url = f"http://127.0.0.1:{port}"

    from webview.util import WebViewException  # type: ignore[import-not-found]

    # If a dashboard is already healthy on this port, reuse it.
    if _is_dashboard_healthy(port):
        console.print(f"[bold]InitRunner Desktop[/bold] (reusing backend on port {port})")
        _start_webview(webview, WebViewException, url)
        return

    # Bind the port now to detect conflicts and avoid a TOCTOU race.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        console.print(f"[red]Port {port} is in use by another process.[/red]")
        raise SystemExit(1) from None

    # Start the embedded backend, passing the pre-bound socket to uvicorn.
    import uvicorn  # type: ignore[import-not-found]

    from initrunner.dashboard.app import create_app
    from initrunner.dashboard.config import DashboardSettings

    settings = DashboardSettings(port=port, extra_role_dirs=roles_dir or [])
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    errors: queue.Queue[BaseException] = queue.Queue()

    def _run_server() -> None:
        try:
            server.run(sockets=[sock])
        except BaseException as exc:
            errors.put(exc)

    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()

    # Wait for the backend to become healthy.
    deadline = time.monotonic() + _HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        # Check if the server thread died.
        try:
            exc = errors.get_nowait()
            console.print(f"[red]Backend failed to start: {exc}[/red]")
            raise SystemExit(1)
        except queue.Empty:
            pass
        if _is_dashboard_healthy(port):
            break
        time.sleep(_HEALTH_INTERVAL)
    else:
        console.print("[red]Backend did not become healthy within 30 seconds.[/red]")
        server.should_exit = True
        raise SystemExit(1)

    console.print(f"[bold]InitRunner Desktop[/bold] at {url}")

    try:
        _start_webview(webview, WebViewException, url)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            server.force_exit = True
            console.print("[yellow]Backend did not shut down cleanly.[/yellow]")


# -- GI bridge ----------------------------------------------------------------


def _ensure_gi() -> None:
    """Make system-installed PyGObject visible inside an isolated venv.

    Probes the base interpreter (the Python the venv was created from) for
    the ``gi`` package and prepends its site-packages directory to
    ``sys.path``.  Only runs on Linux; no-op if ``gi`` is already importable.
    """
    try:
        import gi  # type: ignore[import-not-found]

        del gi  # only checking importability
        return
    except ImportError:
        pass

    if sys.platform != "linux":
        return

    import subprocess

    base_exe = _find_base_executable()
    if not base_exe:
        _fail_gi()

    try:
        result = subprocess.run(  # type: ignore[no-matching-overload]
            [base_exe, "-c", "import gi, pathlib; print(pathlib.Path(gi.__file__).parent.parent)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        _fail_gi()

    if result.returncode != 0:
        _fail_gi()

    site_dir = result.stdout.strip()

    # Temporarily add the system site-packages to import gi (and cairo),
    # then remove it immediately.  Leaving it in sys.path would let older
    # system packages (e.g. typing_extensions) shadow the venv's versions,
    # breaking pydantic and other deps.  Once imported, gi's submodules
    # resolve via gi.__path__, not sys.path.
    already_present = site_dir in sys.path
    if not already_present:
        sys.path.insert(0, site_dir)
    try:
        import gi  # type: ignore[import-not-found]

        del gi
    except ImportError:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        console.print(
            "[red]GTK/WebKit runtime found but incompatible with this "
            f"Python ({ver}).[/red]\n"
            "The distro python3-gi packages are built for a different "
            "Python ABI.\nRecreate the venv with the distro Python, or "
            "install PyGObject manually:\n"
            "  [bold]uv pip install PyGObject pycairo[/bold]"
        )
        raise SystemExit(1) from None
    finally:
        if not already_present:
            try:
                sys.path.remove(site_dir)
            except ValueError:
                pass


def _find_base_executable() -> str | None:
    """Locate the base interpreter this venv was created from."""
    # sys._base_executable is set by venv/virtualenv and points to the
    # real interpreter outside the venv.
    base_exe = getattr(sys, "_base_executable", None)
    if base_exe and Path(base_exe).exists():
        return base_exe

    # Fall back to a version-matched binary under sys.base_prefix.
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidate = Path(sys.base_prefix) / "bin" / f"python{ver}"
    if candidate.exists():
        return str(candidate)

    # Last resort: whatever python3 is on PATH.
    import shutil

    return shutil.which("python3")


def _fail_gi() -> None:
    """Print install hint and exit."""
    hint = _linux_install_hint()
    console.print(f"[red]GTK/WebKit runtime not found.[/red]\n{hint}")
    raise SystemExit(1)


# -- webview helpers -----------------------------------------------------------


def _start_webview(webview: object, WebViewException: type, url: str) -> None:
    """Open the native window, suppressing pywebview's internal traceback noise."""
    import logging

    # pywebview uses logger.exception() for renderer probe failures.
    wv_logger = logging.getLogger("pywebview")
    old_level = wv_logger.level
    wv_logger.setLevel(logging.CRITICAL)
    try:
        webview.create_window(  # type: ignore[union-attr]
            "InitRunner", url, width=1280, height=800, min_size=(900, 600)
        )
        webview.start()  # type: ignore[union-attr]
    except WebViewException as exc:  # type: ignore[invalid-exception-caught]
        _handle_webview_error(exc)
    finally:
        wv_logger.setLevel(old_level)


def _handle_webview_error(exc: Exception) -> None:
    """Handle WebViewException, printing Linux install hints if applicable."""
    msg = str(exc).lower()
    _RENDERER_KEYWORDS = ("gtk", "gi", "webkit", "renderer", "python extensions")
    is_renderer_issue = any(kw in msg for kw in _RENDERER_KEYWORDS)

    if sys.platform == "linux" and is_renderer_issue:
        hint = _linux_install_hint()
        console.print(f"[red]GTK/WebKit runtime not found.[/red]\n{hint}")
        raise SystemExit(1)

    # Not a Linux renderer issue -- re-raise the original error.
    raise exc


def _linux_install_hint() -> str:
    """Return distro-specific install command for GTK/WebKit runtime."""
    os_release = ""
    try:
        with open("/etc/os-release") as f:
            os_release = f.read().lower()
    except OSError:
        pass

    if any(name in os_release for name in ("ubuntu", "debian", "pop!_os", "mint")):
        return (
            "[bold]sudo apt install python3-gi python3-gi-cairo "
            "gir1.2-gtk-3.0 gir1.2-webkit2-4.1[/bold]"
        )
    if "fedora" in os_release:
        return "[bold]sudo dnf install python3-gobject gtk3 webkit2gtk4.1[/bold]"
    if "arch" in os_release:
        return "[bold]sudo pacman -S python-gobject webkit2gtk-4.1[/bold]"
    docs = "https://pywebview.flowrl.com/guide/installation.html"
    return f"See [link={docs}]pywebview install docs[/link]"


def _is_dashboard_healthy(port: int) -> bool:
    """Single stdlib health probe."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read())
            return body.get("status") == "ok"
    except Exception:
        return False
