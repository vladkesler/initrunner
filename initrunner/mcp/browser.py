"""Browser MCP server -- wraps agent-browser CLI for AI agent browser automation."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastmcp import FastMCP
from pydantic import BaseModel

from initrunner.agent._subprocess import SubprocessTimeout, run_subprocess_text
from initrunner.agent._truncate import truncate_output
from initrunner.agent._urls import check_domain_filter, validate_url_ssrf

logger = logging.getLogger(__name__)

_VALID_WAIT_UNTIL = {"none", "load", "domcontentloaded", "networkidle"}


class BrowserMCPConfig(BaseModel):
    server_name: str = "initrunner-browser"
    headless: bool = True
    timeout_seconds: int = 30
    allowed_domains: list[str] = []
    blocked_domains: list[str] = []
    max_output_bytes: int = 512_000
    screenshot_dir: str = ""
    session_name: str = ""
    agent_browser_path: str = "agent-browser"


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_ab(args: list[str], config: BrowserMCPConfig) -> str:
    """Run an agent-browser command and return output.

    Returns output text on success, or an ``Error: ...`` string on failure.
    Never raises.
    """
    binary = config.agent_browser_path
    if not shutil.which(binary):
        return (
            f"Error: '{binary}' not found. Install: npm i -g agent-browser && agent-browser install"
        )

    cmd = [binary]
    if config.session_name:
        cmd += ["--session-name", config.session_name]
    if not config.headless:
        cmd += ["--headed"]
    cmd += args

    try:
        stdout, stderr, rc = run_subprocess_text(cmd, timeout=config.timeout_seconds)
    except SubprocessTimeout:
        return f"Error: command timed out after {config.timeout_seconds}s"
    except Exception as exc:
        return f"Error: failed to run agent-browser: {exc}"

    if rc != 0:
        err_msg = stderr.strip() or stdout.strip() or "command failed"
        return f"Error: {err_msg}"

    return truncate_output(stdout, config.max_output_bytes)


def _check_url(url: str, config: BrowserMCPConfig) -> str | None:
    """Validate a URL for SSRF and domain filters. Returns error or None."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return "Error: file:// URLs are not allowed"
    if parsed.scheme not in ("http", "https", ""):
        return f"Error: unsupported URL scheme: {parsed.scheme}"

    ssrf_err = validate_url_ssrf(url)
    if ssrf_err:
        return ssrf_err

    domain_err = check_domain_filter(url, config.allowed_domains, config.blocked_domains)
    if domain_err:
        return domain_err

    return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_browser_mcp(config: BrowserMCPConfig | None = None) -> FastMCP:
    """Build a FastMCP server wrapping agent-browser CLI."""
    if config is None:
        config = BrowserMCPConfig()

    screenshot_dir = Path(config.screenshot_dir) if config.screenshot_dir else None
    mcp = FastMCP(config.server_name)

    @mcp.tool(description="Navigate to a URL. Returns the page title and current URL.")
    def open_url(url: str, wait_until: str = "networkidle") -> str:
        """Navigate to a URL and return the page title and current URL.

        Args:
            url: The URL to navigate to.
            wait_until: When to consider navigation done.
                One of: none, load, domcontentloaded, networkidle.
        """
        if wait_until not in _VALID_WAIT_UNTIL:
            valid = ", ".join(sorted(_VALID_WAIT_UNTIL))
            return f"Error: invalid wait_until: {wait_until!r}. Expected: {valid}"

        url_err = _check_url(url, config)
        if url_err:
            return url_err

        result = _run_ab(["open", url], config)
        if result.startswith("Error:"):
            return result

        if wait_until != "none":
            wait_result = _run_ab(["wait", "--load", wait_until], config)
            if wait_result.startswith("Error:"):
                return wait_result

        title = _run_ab(["get", "title"], config)
        current_url = _run_ab(["get", "url"], config)

        return f"Navigated to: {current_url.strip()}\nTitle: {title.strip()}"

    @mcp.tool(
        description="Capture a snapshot of interactive elements with reference IDs (@e1, @e2)."
    )
    def snapshot(selector: str = "", interactive_only: bool = True) -> str:
        """Capture a snapshot of the page elements with reference IDs.

        Args:
            selector: CSS selector to scope the snapshot. Empty for full page.
            interactive_only: If true, only show interactive elements.
        """
        args = ["snapshot"]
        if interactive_only:
            args.append("-i")
        if selector:
            args += ["-s", selector]
        return _run_ab(args, config)

    @mcp.tool(description="Click an element by its reference ID.")
    def click(ref: str, wait_until: str = "none") -> str:
        """Click an element identified by its snapshot reference.

        Args:
            ref: Element reference from snapshot (e.g. "@e1").
            wait_until: Wait for page load after click.
                One of: none, load, domcontentloaded, networkidle.
        """
        if wait_until not in _VALID_WAIT_UNTIL:
            valid = ", ".join(sorted(_VALID_WAIT_UNTIL))
            return f"Error: invalid wait_until: {wait_until!r}. Expected: {valid}"

        result = _run_ab(["click", ref], config)
        if result.startswith("Error:"):
            return result

        if wait_until != "none":
            wait_result = _run_ab(["wait", "--load", wait_until], config)
            if wait_result.startswith("Error:"):
                return wait_result

        return result

    @mcp.tool(description="Clear a form field and type new text into it.")
    def fill(ref: str, value: str) -> str:
        """Fill a form field with text (clears existing content first).

        Args:
            ref: Element reference from snapshot (e.g. "@e1").
            value: Text to type into the field.
        """
        return _run_ab(["fill", ref, value], config)

    @mcp.tool(description="Select an option from a dropdown element.")
    def select(ref: str, value: str) -> str:
        """Select a dropdown option by its value or label.

        Args:
            ref: Element reference from snapshot (e.g. "@e1").
            value: Option value or label to select.
        """
        return _run_ab(["select", ref, value], config)

    @mcp.tool(description="Press a keyboard key.")
    def press(key: str) -> str:
        """Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown).

        Args:
            key: Key name to press.
        """
        return _run_ab(["press", key], config)

    @mcp.tool(description="Wait for an element, text, URL pattern, load state, or duration.")
    def wait_for(
        ref: str = "",
        text: str = "",
        url_pattern: str = "",
        load: str = "",
        milliseconds: int = 0,
        state: str = "visible",
    ) -> str:
        """Wait for a condition before continuing.

        Exactly one wait mode must be specified. Providing zero or multiple modes is an error.

        Args:
            ref: Element reference to wait for (e.g. "@e1").
            text: Text string to wait for on the page.
            url_pattern: URL glob pattern to wait for (e.g. "**/dashboard").
            load: Load state to wait for (load, domcontentloaded, networkidle).
            milliseconds: Fixed duration to wait in milliseconds.
            state: Element state for ref waits (visible, hidden, attached, detached).
        """
        modes = []
        if ref:
            modes.append("ref")
        if text:
            modes.append("text")
        if url_pattern:
            modes.append("url_pattern")
        if load:
            modes.append("load")
        if milliseconds > 0:
            modes.append("milliseconds")

        if len(modes) == 0:
            return (
                "Error: wait_for requires exactly one mode."
                " Specify: ref, text, url_pattern, load, or milliseconds."
            )
        if len(modes) > 1:
            got = ", ".join(modes)
            return f"Error: wait_for requires exactly one mode, got: {got}."

        if ref:
            args = ["wait", ref]
            if state != "visible":
                args += ["--state", state]
            return _run_ab(args, config)
        if text:
            return _run_ab(["wait", "--text", text], config)
        if url_pattern:
            return _run_ab(["wait", "--url", url_pattern], config)
        if load:
            return _run_ab(["wait", "--load", load], config)
        return _run_ab(["wait", str(milliseconds)], config)

    @mcp.tool(description="Get text content of the page or a specific element.")
    def get_text(ref: str = "") -> str:
        """Get text content from the page or an element.

        Args:
            ref: Element reference (e.g. "@e1"). Empty for full page text.
        """
        args = ["get", "text"]
        if ref:
            args.append(ref)
        return _run_ab(args, config)

    @mcp.tool(description="Get the current page URL.")
    def get_url() -> str:
        """Get the current page URL."""
        return _run_ab(["get", "url"], config)

    @mcp.tool(description="Get the current page title.")
    def get_title() -> str:
        """Get the current page title."""
        return _run_ab(["get", "title"], config)

    @mcp.tool(description="Take a screenshot and save it to disk. Returns the file path.")
    def screenshot(full_page: bool = False, annotate: bool = False) -> str:
        """Take a screenshot of the current page.

        Args:
            full_page: Capture the full scrollable page, not just the viewport.
            annotate: Add numbered element labels to the screenshot.
        """
        save_dir = screenshot_dir or Path(tempfile.mkdtemp(prefix="initrunner_browser_"))
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        dest = save_dir / "screenshot.png"
        args = ["screenshot", str(dest)]
        if full_page:
            args.append("--full")
        if annotate:
            args.append("--annotate")

        result = _run_ab(args, config)
        if result.startswith("Error:"):
            return result

        if dest.exists():
            return str(dest)
        return result

    @mcp.tool(description="Close the browser session.")
    def close_browser() -> str:
        """Close the current browser session."""
        return _run_ab(["close"], config)

    return mcp


# ---------------------------------------------------------------------------
# Dedicated entrypoint for initrunner-browser-mcp console script
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``initrunner-browser-mcp`` console script."""
    mcp = build_browser_mcp()
    mcp.run(transport="stdio")
