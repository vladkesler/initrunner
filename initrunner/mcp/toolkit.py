"""MCP toolkit — expose InitRunner tools directly as MCP tools (no agent/LLM)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from initrunner.agent._env import resolve_env_vars

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 65_536


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ToolkitSearchConfig(BaseModel):
    provider: str = "duckduckgo"
    api_key: str = ""
    max_results: int = 10
    safe_search: bool = True
    timeout_seconds: int = 15


class ToolkitWebReaderConfig(BaseModel):
    timeout_seconds: int = 15
    max_bytes: int = 512_000


class ToolkitCsvAnalysisConfig(BaseModel):
    root_path: str = "."
    max_rows: int = 1000
    max_file_size_mb: float = 10.0
    delimiter: str = ","


class ToolkitDatetimeConfig(BaseModel):
    default_timezone: str = "UTC"


class ToolkitSqlConfig(BaseModel):
    database: str
    read_only: bool = True


class ToolkitHttpConfig(BaseModel):
    base_url: str
    allowed_methods: list[str] = Field(default_factory=lambda: ["GET"])
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 30


class ToolkitEmailConfig(BaseModel):
    imap_host: str
    smtp_host: str = ""
    imap_port: int = 993
    smtp_port: int = 587
    username: str
    password: str
    use_ssl: bool = True
    default_folder: str = "INBOX"
    read_only: bool = True
    max_results: int = 20
    max_body_chars: int = 50_000
    timeout_seconds: int = 30


class ToolkitAudioConfig(BaseModel):
    youtube_languages: list[str] = Field(default_factory=lambda: ["en"])
    include_timestamps: bool = False
    max_transcript_chars: int = 50_000


class ToolkitConfig(BaseModel):
    server_name: str = "initrunner-toolkit"
    tools: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Default tools (no API key / external state required)
# ---------------------------------------------------------------------------

_DEFAULT_TOOLS = {"search", "web_reader", "csv_analysis", "datetime"}
_ALL_TOOLS = _DEFAULT_TOOLS | {"sql", "http", "email", "audio"}


# ---------------------------------------------------------------------------
# Registrar: search
# ---------------------------------------------------------------------------


def _register_search(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitSearchConfig(**raw_config)
    api_key = resolve_env_vars(cfg.api_key)

    from initrunner.agent.tools.search import _PROVIDERS, _do_search

    provider_fn = _PROVIDERS.get(cfg.provider)
    if provider_fn is None:
        raise ValueError(
            f"Unknown search provider: {cfg.provider!r}. Available: {', '.join(_PROVIDERS)}"
        )

    @mcp.tool(description="Search the web for information using DuckDuckGo or other providers.")
    def web_search(query: str, num_results: int = 5) -> str:
        """Search the web for information.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
        """
        return _do_search(
            query,
            num_results,
            cfg.max_results,
            cfg.safe_search,
            api_key,
            cfg.timeout_seconds,
            provider_fn,
        )

    @mcp.tool(description="Search for recent news articles.")
    def news_search(query: str, num_results: int = 5, days_back: int = 7) -> str:
        """Search for recent news articles.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
            days_back: How many days back to search (default 7).
        """
        return _do_search(
            query,
            num_results,
            cfg.max_results,
            cfg.safe_search,
            api_key,
            cfg.timeout_seconds,
            provider_fn,
            news=True,
            days_back=days_back,
        )


# ---------------------------------------------------------------------------
# Registrar: web_reader
# ---------------------------------------------------------------------------


def _register_web_reader(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitWebReaderConfig(**raw_config)

    @mcp.tool(
        description=(
            "Fetch a URL and return its content as clean markdown. Includes SSRF protection."
        )
    )
    def fetch_page(url: str) -> str:
        """Fetch a web page and return its content as clean markdown.

        Args:
            url: The URL to fetch (must be http or https).
        """
        from initrunner._html import fetch_url_as_markdown
        from initrunner.agent._urls import SSRFBlocked

        try:
            return fetch_url_as_markdown(url, timeout=cfg.timeout_seconds, max_bytes=cfg.max_bytes)
        except SSRFBlocked as e:
            return str(e)
        except Exception as e:
            return f"Error fetching URL: {e}"


# ---------------------------------------------------------------------------
# Registrar: csv_analysis
# ---------------------------------------------------------------------------


def _register_csv_analysis(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitCsvAnalysisConfig(**raw_config)
    root = Path(cfg.root_path).resolve()

    from initrunner.agent.tools.csv_analysis import (
        _do_inspect_csv,
        _do_query_csv,
        _do_summarize_csv,
    )

    @mcp.tool(
        description=(
            "Inspect a CSV file: show column names, inferred types, row count, and first 5 rows."
        )
    )
    def inspect_csv(path: str) -> str:
        """Inspect a CSV file: show column names, inferred types, row count, and first 5 rows.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
        """
        return _do_inspect_csv(
            root / path, root, path, cfg.max_rows, cfg.delimiter, cfg.max_file_size_mb
        )

    @mcp.tool(
        description=(
            "Summarize a CSV file or a single column with statistics "
            "(numeric: min/max/mean/median/stdev; categorical: unique count and top values)."
        )
    )
    def summarize_csv(path: str, column: str = "") -> str:
        """Summarize a CSV file or a single column.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
            column: Column name to summarize. Leave empty to summarize all columns.
        """
        return _do_summarize_csv(
            root / path, root, path, cfg.max_rows, cfg.delimiter, cfg.max_file_size_mb, column
        )

    @mcp.tool(description="Filter and return rows from a CSV file as a markdown table.")
    def query_csv(
        path: str,
        filter_column: str = "",
        filter_value: str = "",
        columns: str = "",
        limit: int = 50,
    ) -> str:
        """Filter and return rows from a CSV file as a markdown table.

        Args:
            path: Path to the CSV file, relative to the configured root directory.
            filter_column: Column name to filter on. Leave empty to return all rows.
            filter_value: Exact value to match in filter_column.
            columns: Comma-separated list of column names to include. Leave empty for all.
            limit: Maximum number of rows to return (default 50).
        """
        return _do_query_csv(
            root / path,
            root,
            path,
            cfg.max_rows,
            cfg.delimiter,
            cfg.max_file_size_mb,
            filter_column,
            filter_value,
            columns,
            limit,
        )


# ---------------------------------------------------------------------------
# Registrar: datetime
# ---------------------------------------------------------------------------


def _register_datetime(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitDatetimeConfig(**raw_config)

    @mcp.tool(description="Get the current date and time in a specified timezone.")
    def current_time(tz: str = "") -> str:
        """Get the current date and time.

        Args:
            tz: Timezone name (e.g. 'America/New_York', 'UTC'). Defaults to configured timezone.
        """
        import zoneinfo

        tz_name = tz or cfg.default_timezone
        try:
            tzinfo = zoneinfo.ZoneInfo(tz_name)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            return f"Error: unknown timezone: {tz_name!r}"

        now = datetime.now(tzinfo)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z (%z)")

    @mcp.tool(description="Parse a date string and return it in ISO 8601 format.")
    def parse_date(date_string: str, tz: str = "") -> str:
        """Parse a date/time string into ISO 8601 format.

        Args:
            date_string: Date string to parse (e.g. '2024-01-15', 'January 15, 2024 3pm').
            tz: Timezone to apply if the input has no timezone info.
        """
        import zoneinfo

        from dateutil import parser as dateutil_parser  # type: ignore[import-not-found]

        tz_name = tz or cfg.default_timezone
        try:
            tzinfo = zoneinfo.ZoneInfo(tz_name)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            return f"Error: unknown timezone: {tz_name!r}"

        try:
            dt = dateutil_parser.parse(date_string)
        except (ValueError, OverflowError) as e:
            return f"Error: could not parse date: {e}"

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo)

        return dt.isoformat()


# ---------------------------------------------------------------------------
# Registrar: sql (opt-in)
# ---------------------------------------------------------------------------


def _register_sql(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitSqlConfig(**raw_config)
    db_path = resolve_env_vars(cfg.database)

    from initrunner.agent._truncate import truncate_output

    @mcp.tool(description="Execute a SQL query against a SQLite database.")
    def sql_query(query: str) -> str:
        """Execute a SQL query against the configured SQLite database.

        Args:
            query: SQL query to execute. Write operations are blocked if read_only is true.
        """
        if cfg.read_only:
            normalized = query.strip().upper()
            if not normalized.startswith("SELECT") and not normalized.startswith("PRAGMA"):
                return "Error: only SELECT and PRAGMA queries are allowed in read-only mode"

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(query)
                if cursor.description is None:
                    conn.commit()
                    return f"Query executed successfully. Rows affected: {cursor.rowcount}"
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchmany(1000)
                result_rows = [dict(row) for row in rows]

                if not result_rows:
                    return "Query returned 0 rows."

                lines = ["| " + " | ".join(columns) + " |"]
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in result_rows:
                    lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
                output = f"**Rows:** {len(result_rows)}\n\n" + "\n".join(lines)
                return truncate_output(output, _MAX_OUTPUT_BYTES)
            finally:
                conn.close()
        except sqlite3.Error as e:
            return f"SQL error: {e}"
        except Exception as e:
            return f"Error: {e}"


# ---------------------------------------------------------------------------
# Registrar: http (opt-in)
# ---------------------------------------------------------------------------


def _register_http(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitHttpConfig(**raw_config)
    allowed_methods = {m.upper() for m in cfg.allowed_methods}

    from initrunner.agent._truncate import truncate_output

    @mcp.tool(description="Make an HTTP request to the configured base URL.")
    def http_request(method: str, path: str, body: str = "") -> str:
        """Make an HTTP request to the configured base URL.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.).
            path: URL path to append to the base URL.
            body: Request body (for POST/PUT).
        """
        import httpx

        from initrunner.agent._urls import SSRFBlocked, SSRFSafeTransport

        method = method.upper()
        if method not in allowed_methods:
            return f"Error: HTTP method {method} is not allowed"
        url = f"{cfg.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            with httpx.Client(
                headers=cfg.headers,
                timeout=cfg.timeout_seconds,
                transport=SSRFSafeTransport(),
            ) as client:
                resp = client.request(method, url, content=body if body else None)
                text = truncate_output(resp.text, 102_400)
                return f"HTTP {resp.status_code}\n{text}"
        except SSRFBlocked as e:
            return str(e)
        except httpx.HTTPError as e:
            return f"HTTP error: {e}"


# ---------------------------------------------------------------------------
# Registrar: email (opt-in)
# ---------------------------------------------------------------------------


def _register_email(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitEmailConfig(**raw_config)
    username = resolve_env_vars(cfg.username)
    password = resolve_env_vars(cfg.password)

    from initrunner.agent.tools.email_tools import (
        ImapParams,
        _do_list_folders,
        _do_read_email,
        _do_search_inbox,
        _do_send_email,
    )

    params = ImapParams(
        host=cfg.imap_host,
        port=cfg.imap_port,
        username=username,
        password=password,
        use_ssl=cfg.use_ssl,
        timeout_seconds=cfg.timeout_seconds,
    )

    @mcp.tool(description="Search for emails using IMAP SEARCH syntax (RFC 3501).")
    def search_inbox(query: str = "ALL", folder: str = "", limit: int = 0) -> str:
        """Search for emails using IMAP SEARCH syntax (RFC 3501).

        Args:
            query: IMAP SEARCH query string (e.g. 'ALL', 'UNSEEN', 'FROM "sender@example.com"').
            folder: Mailbox folder to search. Defaults to configured default_folder.
            limit: Maximum number of results. 0 means use config default.
        """
        return _do_search_inbox(
            params,
            cfg.default_folder,
            cfg.max_results,
            cfg.max_body_chars,
            query,
            folder,
            limit,
        )

    @mcp.tool(description="Read the full content of an email by its Message-ID.")
    def read_email(message_id: str, folder: str = "") -> str:
        """Read the full content of an email by its Message-ID.

        Args:
            message_id: The Message-ID header value (e.g. "<abc123@example.com>").
            folder: Mailbox folder to search in. Defaults to configured default_folder.
        """
        return _do_read_email(params, cfg.default_folder, cfg.max_body_chars, message_id, folder)

    @mcp.tool(description="List all available mailbox folders.")
    def list_folders() -> str:
        """List all available mailbox folders."""
        return _do_list_folders(params)

    if not cfg.read_only:

        @mcp.tool(description="Send an email message via SMTP.")
        def send_email(
            to: str,
            subject: str,
            body: str,
            reply_to: str = "",
            cc: str = "",
        ) -> str:
            """Send an email message.

            Args:
                to: Recipient email address.
                subject: Email subject line.
                body: Plain text email body.
                reply_to: Message-ID to reply to.
                cc: CC recipients (comma-separated).
            """
            return _do_send_email(
                cfg.smtp_host,
                cfg.smtp_port,
                username,
                password,
                cfg.timeout_seconds,
                to,
                subject,
                body,
                reply_to,
                cc,
            )


# ---------------------------------------------------------------------------
# Registrar: audio (opt-in — YouTube transcripts only, no LLM transcription)
# ---------------------------------------------------------------------------


def _register_audio(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitAudioConfig(**raw_config)

    from initrunner.agent.tools.audio import _do_get_youtube_transcript

    @mcp.tool(description="Fetch the transcript/captions for a YouTube video.")
    def get_youtube_transcript(url: str, language: str = "") -> str:
        """Fetch the transcript/captions for a YouTube video.

        Args:
            url: YouTube video URL.
            language: Language code (e.g. 'en', 'es'). Leave empty for configured default.
        """
        return _do_get_youtube_transcript(
            url,
            cfg.youtube_languages,
            cfg.include_timestamps,
            cfg.max_transcript_chars,
            language,
        )


# ---------------------------------------------------------------------------
# Registrar map & builder
# ---------------------------------------------------------------------------

_TOOLKIT_REGISTRARS: dict[str, Any] = {
    "search": _register_search,
    "web_reader": _register_web_reader,
    "csv_analysis": _register_csv_analysis,
    "datetime": _register_datetime,
    "sql": _register_sql,
    "http": _register_http,
    "email": _register_email,
    "audio": _register_audio,
}


def build_toolkit(
    config: ToolkitConfig | None = None,
    *,
    tool_names: list[str] | None = None,
) -> FastMCP:
    """Build a FastMCP server exposing InitRunner tools directly (no agent/LLM).

    Parameters:
        config: Optional toolkit configuration. If ``None``, uses defaults.
        tool_names: Explicit list of tool names to register. Overrides ``config.tools``.
    """
    if config is None:
        config = ToolkitConfig()

    mcp = FastMCP(config.server_name)

    # Determine which tools to register
    if tool_names is not None:
        # CLI --tools flag: register specified tools with config from file or defaults
        selected = tool_names
    elif config.tools:
        # Config file: register only tools listed in config
        selected = list(config.tools.keys())
    else:
        # No config, no --tools: register default tools
        selected = sorted(_DEFAULT_TOOLS)

    for name in selected:
        if name not in _TOOLKIT_REGISTRARS:
            raise ValueError(
                f"Unknown toolkit tool: {name!r}. Available: {', '.join(sorted(_ALL_TOOLS))}"
            )
        raw_config = config.tools.get(name, {})
        _TOOLKIT_REGISTRARS[name](mcp, raw_config)

    return mcp


def load_toolkit_config(config_path: Path) -> ToolkitConfig:
    """Load a ToolkitConfig from a YAML file with ``${VAR}`` interpolation."""
    import yaml

    text = config_path.read_text(encoding="utf-8")
    text = resolve_env_vars(text)
    data = yaml.safe_load(text) or {}
    return ToolkitConfig(**data)
