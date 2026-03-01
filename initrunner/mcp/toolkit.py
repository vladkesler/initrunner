"""MCP toolkit — expose InitRunner tools directly as MCP tools (no agent/LLM)."""

from __future__ import annotations

import csv
import logging
import sqlite3
import statistics
from collections import Counter
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
    timeout: int = 15
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
    timeout: int = 30


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

    from initrunner.agent.tools.search import _PROVIDERS, _format_results

    provider_fn = _PROVIDERS.get(cfg.provider)
    if provider_fn is None:
        raise ValueError(
            f"Unknown search provider: {cfg.provider!r}. Available: {', '.join(_PROVIDERS)}"
        )

    from initrunner.agent._truncate import truncate_output

    @mcp.tool(description="Search the web for information using DuckDuckGo or other providers.")
    def web_search(query: str, num_results: int = 5) -> str:
        """Search the web for information.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
        """
        try:
            results = provider_fn(
                query=query,
                max_results=min(num_results, cfg.max_results),
                safe_search=cfg.safe_search,
                api_key=api_key,
                timeout=cfg.timeout_seconds,
                news=False,
            )
            return truncate_output(_format_results(results), _MAX_OUTPUT_BYTES)
        except ImportError as e:
            return f"Error: {e}"
        except TimeoutError:
            return f"Error: search timed out after {cfg.timeout_seconds}s"
        except Exception as e:
            return f"Error: search failed: {e}"

    @mcp.tool(description="Search for recent news articles.")
    def news_search(query: str, num_results: int = 5, days_back: int = 7) -> str:
        """Search for recent news articles.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (default 5).
            days_back: How many days back to search (default 7).
        """
        try:
            results = provider_fn(
                query=query,
                max_results=min(num_results, cfg.max_results),
                safe_search=cfg.safe_search,
                api_key=api_key,
                timeout=cfg.timeout_seconds,
                news=True,
                days_back=days_back,
            )
            return truncate_output(_format_results(results), _MAX_OUTPUT_BYTES)
        except ImportError as e:
            return f"Error: {e}"
        except TimeoutError:
            return f"Error: search timed out after {cfg.timeout_seconds}s"
        except Exception as e:
            return f"Error: search failed: {e}"


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
            return fetch_url_as_markdown(url, timeout=cfg.timeout, max_bytes=cfg.max_bytes)
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

    from initrunner.agent._paths import validate_path_within
    from initrunner.agent._truncate import truncate_output
    from initrunner.agent.tools.csv_analysis import (
        _check_file_size,
        _infer_type,
        _rows_to_md_table,
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
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, cfg.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=cfg.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            headers = list(reader.fieldnames)

            rows: list[dict[str, str]] = []
            truncated = False
            for row in reader:
                if len(rows) >= cfg.max_rows:
                    truncated = True
                    break
                rows.append(dict(row))
        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        col_values: dict[str, list[str]] = {h: [] for h in headers}
        for row in rows:
            for h in headers:
                v = row.get(h, "")
                if v and len(col_values[h]) < 100:
                    col_values[h].append(v)

        col_types = {h: _infer_type(col_values[h]) for h in headers}

        lines: list[str] = [
            f"**File:** {path}",
            f"**Rows inspected:** {len(rows)}" + (" (truncated)" if truncated else ""),
            f"**Columns:** {len(headers)}",
            "",
            "| Column | Type |",
            "| --- | --- |",
        ]
        for h in headers:
            lines.append(f"| {h} | {col_types[h]} |")

        lines.append("")
        lines.append("**First 5 rows:**")
        lines.append("")
        lines.append(_rows_to_md_table(headers, rows[:5]))

        return truncate_output("\n".join(lines), _MAX_OUTPUT_BYTES)

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
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, cfg.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=cfg.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            headers = list(reader.fieldnames)

            rows: list[dict[str, str]] = []
            for row in reader:
                if len(rows) >= cfg.max_rows:
                    break
                rows.append(dict(row))
        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        def _col_summary(col_name: str) -> str:
            non_empty = [row.get(col_name, "") for row in rows if row.get(col_name, "")]
            nums: list[float] = []
            for v in non_empty:
                try:
                    nums.append(float(v))
                except ValueError:
                    break
            else:
                if nums:
                    mn = min(nums)
                    mx = max(nums)
                    mean = statistics.mean(nums)
                    median = statistics.median(nums)
                    if len(nums) >= 2:
                        stdev_str = f"{statistics.stdev(nums):.4g}"
                    else:
                        stdev_str = "N/A (< 2 values)"
                    return (
                        f"numeric | count_non_empty={len(non_empty)}, min={mn:.4g}, "
                        f"max={mx:.4g}, mean={mean:.4g}, median={median:.4g}, stdev={stdev_str}"
                    )
                return "numeric | (no values)"
            counter = Counter(non_empty)
            top10 = counter.most_common(10)
            top_str = ", ".join(f"{v!r}:{c}" for v, c in top10)
            return f"categorical | unique={len(counter)}, top values: {top_str}"

        if column:
            if column not in headers:
                avail = ", ".join(headers)
                return f"Error: column '{column}' not found. Available: {avail}"
            output = (
                f"**Column:** {column}\n**Summary:** {_col_summary(column)}\n**Rows:** {len(rows)}"
            )
        else:
            lines: list[str] = [
                f"**File:** {path}",
                f"**Rows:** {len(rows)}",
                "",
                "| Column | Summary |",
                "| --- | --- |",
            ]
            for h in headers:
                lines.append(f"| {h} | {_col_summary(h)} |")
            output = "\n".join(lines)

        return truncate_output(output, _MAX_OUTPUT_BYTES)

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
        raw = root / path
        err, target = validate_path_within(raw, [root], allowed_ext={".csv"}, reject_symlinks=True)
        if err:
            return err

        size_err = _check_file_size(target, cfg.max_file_size_mb)
        if size_err:
            return size_err

        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except UnicodeDecodeError:
            return "Error: file is not valid UTF-8"

        try:
            reader = csv.DictReader(text.splitlines(), delimiter=cfg.delimiter)
            if reader.fieldnames is None:
                return "Error: could not parse CSV: no headers found"
            all_headers = list(reader.fieldnames)

            col_list = (
                [c.strip() for c in columns.split(",") if c.strip()] if columns else all_headers
            )

            unknown = [c for c in col_list if c not in all_headers]
            if filter_column and filter_column not in all_headers:
                unknown.append(filter_column)
            if unknown:
                avail = ", ".join(all_headers)
                return f"Error: unknown column(s): {', '.join(unknown)}. Available: {avail}"

            effective_limit = min(limit, cfg.max_rows)
            rows_read = 0
            matched: list[dict[str, str]] = []

            for row in reader:
                if rows_read >= cfg.max_rows:
                    break
                rows_read += 1
                if filter_column and filter_value:
                    if row.get(filter_column, "") != filter_value:
                        continue
                if len(matched) < effective_limit:
                    matched.append({c: row.get(c, "") for c in col_list})
        except csv.Error as e:
            return f"Error: could not parse CSV: {e}"

        lines: list[str] = [
            f"**File:** {path}",
            f"**Rows inspected:** {rows_read}, **Rows matched:** {len(matched)}",
            "",
            _rows_to_md_table(all_headers if not columns else col_list, matched),
        ]
        return truncate_output("\n".join(lines), _MAX_OUTPUT_BYTES)


def _rows_to_md_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    """Format rows as a markdown table."""
    if not rows:
        return "(no rows)"
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row.get(h, "") for h in headers) + " |")
    return "\n".join(lines)


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
                timeout=cfg.timeout,
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
    import email as email_mod
    import email.header
    import email.mime.multipart
    import email.mime.text
    import imaplib
    import re
    import smtplib

    cfg = ToolkitEmailConfig(**raw_config)
    username = resolve_env_vars(cfg.username)
    password = resolve_env_vars(cfg.password)

    from initrunner.agent._truncate import truncate_output
    from initrunner.agent.tools.email_tools import _decode_header, _extract_body

    def _imap_connect() -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        if cfg.use_ssl:
            conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
        else:
            conn = imaplib.IMAP4(cfg.imap_host, cfg.imap_port)
        conn.sock.settimeout(cfg.timeout_seconds)
        conn.login(username, password)
        return conn

    @mcp.tool(description="Search for emails using IMAP SEARCH syntax (RFC 3501).")
    def search_inbox(query: str = "ALL", folder: str = "", limit: int = 0) -> str:
        """Search for emails using IMAP SEARCH syntax (RFC 3501).

        Args:
            query: IMAP SEARCH query string (e.g. 'ALL', 'UNSEEN', 'FROM "sender@example.com"').
            folder: Mailbox folder to search. Defaults to configured default_folder.
            limit: Maximum number of results. 0 means use config default.
        """
        conn = None
        try:
            conn = _imap_connect()
            target_folder = folder or cfg.default_folder
            conn.select(target_folder, readonly=True)

            status, data = conn.search(None, query)
            if status != "OK":
                return f"IMAP error: search returned {status}"

            msg_nums = data[0].split() if data[0] else []
            msg_nums.reverse()

            max_count = limit if limit > 0 else cfg.max_results
            msg_nums = msg_nums[:max_count]

            if not msg_nums:
                return "No messages found."

            results: list[str] = []
            for num in msg_nums:
                status, msg_data = conn.fetch(
                    num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
                )
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0]
                if isinstance(raw, tuple):
                    header_bytes = raw[1]
                else:
                    continue
                msg = email_mod.message_from_bytes(header_bytes)
                mid = msg.get("Message-ID", "").strip()
                frm = _decode_header(msg.get("From", ""))
                subj = _decode_header(msg.get("Subject", ""))
                date = msg.get("Date", "")
                results.append(f"ID: {mid}\nFrom: {frm}\nSubject: {subj}\nDate: {date}")

            output = "\n---\n".join(results)
            return truncate_output(output, cfg.max_body_chars)
        except imaplib.IMAP4.error as e:
            return f"IMAP error: {e}"
        except OSError as e:
            return f"IMAP connection error: {e}"
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    @mcp.tool(description="Read the full content of an email by its Message-ID.")
    def read_email(message_id: str, folder: str = "") -> str:
        """Read the full content of an email by its Message-ID.

        Args:
            message_id: The Message-ID header value (e.g. "<abc123@example.com>").
            folder: Mailbox folder to search in. Defaults to configured default_folder.
        """
        conn = None
        try:
            conn = _imap_connect()
            target_folder = folder or cfg.default_folder
            conn.select(target_folder, readonly=False)

            status, data = conn.search(None, f'HEADER Message-ID "{message_id}"')
            if status != "OK" or not data[0]:
                return f"Email not found: {message_id}"

            msg_nums = data[0].split()
            num = msg_nums[0]

            status, msg_data = conn.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                return f"Failed to fetch email: {message_id}"

            raw = msg_data[0]
            if isinstance(raw, tuple):
                raw_bytes = raw[1]
            else:
                return f"Failed to fetch email: {message_id}"

            msg = email_mod.message_from_bytes(raw_bytes)

            headers: list[str] = []
            for hdr in ("Subject", "From", "To", "Cc", "Date"):
                val = msg.get(hdr)
                if val:
                    headers.append(f"{hdr}: {_decode_header(val)}")

            body = _extract_body(msg, cfg.max_body_chars)

            output = "\n".join(headers) + "\n\n" + body
            return truncate_output(output, cfg.max_body_chars)
        except imaplib.IMAP4.error as e:
            return f"IMAP error: {e}"
        except OSError as e:
            return f"IMAP connection error: {e}"
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    @mcp.tool(description="List all available mailbox folders.")
    def list_folders() -> str:
        """List all available mailbox folders."""
        conn = None
        try:
            conn = _imap_connect()
            status, data = conn.list()
            if status != "OK":
                return f"IMAP error: list returned {status}"

            folders: list[str] = []
            for item in data:
                if item is None:
                    continue
                if isinstance(item, bytes):
                    line = item.decode("utf-8", errors="replace")
                else:
                    line = str(item)
                match = re.search(r'"([^"]*)"$', line)
                if match:
                    folder_name = match.group(1)
                elif " " in line:
                    folder_name = line.rsplit(" ", 1)[-1]
                else:
                    continue
                if folder_name:
                    folders.append(folder_name)

            folders.sort()
            return "\n".join(folders) if folders else "(no folders found)"
        except imaplib.IMAP4.error as e:
            return f"IMAP error: {e}"
        except OSError as e:
            return f"IMAP connection error: {e}"
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

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
            server = None
            try:
                msg = email.mime.multipart.MIMEMultipart("alternative")
                msg["From"] = username
                msg["To"] = to
                msg["Subject"] = subject
                if cc:
                    msg["Cc"] = cc
                if reply_to:
                    safe_reply_to = reply_to.replace("\r", "").replace("\n", "")
                    msg["In-Reply-To"] = safe_reply_to
                    msg["References"] = safe_reply_to

                msg.attach(email.mime.text.MIMEText(body, "plain"))

                recipients = [addr.strip() for addr in to.split(",")]
                if cc:
                    recipients.extend(addr.strip() for addr in cc.split(","))

                if cfg.smtp_port == 465:
                    server = smtplib.SMTP_SSL(
                        cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_seconds
                    )
                else:
                    server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout_seconds)
                    server.starttls()

                server.login(username, password)
                server.sendmail(username, recipients, msg.as_string())

                return f"Email sent to {to}" + (f" (cc: {cc})" if cc else "")
            except smtplib.SMTPException as e:
                return f"SMTP error: {e}"
            except OSError as e:
                return f"SMTP connection error: {e}"
            finally:
                if server is not None:
                    try:
                        server.quit()
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# Registrar: audio (opt-in — YouTube transcripts only, no LLM transcription)
# ---------------------------------------------------------------------------


def _register_audio(mcp: FastMCP, raw_config: dict[str, Any]) -> None:
    cfg = ToolkitAudioConfig(**raw_config)

    from initrunner.agent.tools.audio import _extract_video_id

    @mcp.tool(description="Fetch the transcript/captions for a YouTube video.")
    def get_youtube_transcript(url: str, language: str = "") -> str:
        """Fetch the transcript/captions for a YouTube video.

        Args:
            url: YouTube video URL.
            language: Language code (e.g. 'en', 'es'). Leave empty for configured default.
        """
        try:
            from youtube_transcript_api import (  # type: ignore[import-not-found]
                YouTubeTranscriptApi,
            )
            from youtube_transcript_api._errors import (  # type: ignore[import-not-found]
                NoTranscriptFound,
                TranscriptsDisabled,
            )
        except ImportError:
            return (
                "Error: youtube-transcript-api is required. "
                "Install with: pip install initrunner[audio]"
            )

        video_id = _extract_video_id(url)
        if not video_id:
            return f"Error: could not extract a YouTube video ID from URL: {url!r}"

        langs = [language] if language else cfg.youtube_languages
        try:
            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(video_id)
            try:
                transcript = transcript_list.find_transcript(langs)
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(langs)
            entries = transcript.fetch()
        except TranscriptsDisabled:
            return "Error: transcripts are disabled for this video."
        except NoTranscriptFound:
            return f"Error: no transcript found for video {video_id!r} in languages {langs}."
        except Exception as exc:
            return f"Error fetching transcript: {exc}"

        parts: list[str] = []
        for entry in entries:
            text = entry.text
            if cfg.include_timestamps:
                text = f"[{entry.start:.1f}s] {text}"
            parts.append(text)

        result = " ".join(parts)
        if len(result) > cfg.max_transcript_chars:
            result = result[: cfg.max_transcript_chars] + "\n[truncated]"
        return result


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
