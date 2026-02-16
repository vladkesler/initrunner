"""Email tools: search_inbox, read_email, list_folders, send_email."""

from __future__ import annotations

import email
import email.header
import email.mime.multipart
import email.mime.text
import email.utils
import imaplib
import re
import smtplib
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._env import resolve_env_vars
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema import EmailToolConfig
from initrunner.agent.tools._registry import register_tool

if TYPE_CHECKING:
    from initrunner.agent.tools._registry import ToolBuildContext


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _decode_header(value: str) -> str:
    """Decode an RFC 2047 encoded header value."""
    parts = email.header.decode_header(value)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _html_to_markdown(html: str) -> str:
    """Convert HTML to markdown with graceful fallback."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        cleaned = str(soup)
    except Exception:
        cleaned = html

    try:
        import markdownify

        return markdownify.markdownify(cleaned, strip=["img"])
    except ImportError:
        pass

    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(separator="\n")
    except Exception:
        return html


def _extract_body(msg: email.message.Message, max_chars: int = 50_000) -> str:
    """Extract the text body from a message, preferring plain text over HTML."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = payload.decode("latin-1")
            if content_type == "text/plain":
                plain_parts.append(text)
            elif content_type == "text/html":
                html_parts.append(text)
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = payload.decode("latin-1")
            if content_type == "text/plain":
                plain_parts.append(text)
            elif content_type == "text/html":
                html_parts.append(text)

    if plain_parts:
        body = "\n".join(plain_parts)
    elif html_parts:
        body = _html_to_markdown("\n".join(html_parts))
    else:
        body = "(no text content)"

    return truncate_output(body, max_chars)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@register_tool("email", EmailToolConfig)
def build_email_toolset(
    config: EmailToolConfig,
    ctx: ToolBuildContext,
) -> FunctionToolset:
    """Build a FunctionToolset for email operations."""
    username = resolve_env_vars(config.username)
    password = resolve_env_vars(config.password)

    def _imap_connect() -> imaplib.IMAP4_SSL | imaplib.IMAP4:
        if config.use_ssl:
            conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
        else:
            conn = imaplib.IMAP4(config.imap_host, config.imap_port)
        conn.sock.settimeout(config.timeout_seconds)
        conn.login(username, password)
        return conn

    toolset = FunctionToolset()

    @toolset.tool
    def search_inbox(query: str = "ALL", folder: str = "", limit: int = 0) -> str:
        """Search for emails using IMAP SEARCH syntax (RFC 3501).

        Common query examples:
        - "ALL" — all messages
        - "UNSEEN" — unread messages
        - "FROM \\"sender@example.com\\""
        - "SUBJECT \\"Hello World\\"" — always quote multi-word string values
        - "SINCE 01-Jan-2025"
        - "UNSEEN FROM \\"boss@example.com\\""

        Args:
            query: IMAP SEARCH query string. Defaults to "ALL".
            folder: Mailbox folder to search. Defaults to configured default_folder.
            limit: Maximum number of results to return. 0 means use config default.
        """
        conn = None
        try:
            conn = _imap_connect()
            target_folder = folder or config.default_folder
            conn.select(target_folder, readonly=True)

            status, data = conn.search(None, query)
            if status != "OK":
                return f"IMAP error: search returned {status}"

            msg_nums = data[0].split() if data[0] else []
            # Newest first
            msg_nums.reverse()

            max_count = limit if limit > 0 else config.max_results
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
                msg = email.message_from_bytes(header_bytes)
                mid = msg.get("Message-ID", "").strip()
                frm = _decode_header(msg.get("From", ""))
                subj = _decode_header(msg.get("Subject", ""))
                date = msg.get("Date", "")
                results.append(f"ID: {mid}\nFrom: {frm}\nSubject: {subj}\nDate: {date}")

            output = "\n---\n".join(results)
            return truncate_output(output, config.max_body_chars)
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

    @toolset.tool
    def read_email(message_id: str, folder: str = "") -> str:
        """Read the full content of an email by its Message-ID.

        Args:
            message_id: The Message-ID header value (e.g. "<abc123@example.com>").
            folder: Mailbox folder to search in. Defaults to configured default_folder.
        """
        conn = None
        try:
            conn = _imap_connect()
            target_folder = folder or config.default_folder
            conn.select(target_folder, readonly=False)

            # Search by Message-ID header
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

            msg = email.message_from_bytes(raw_bytes)

            headers: list[str] = []
            for hdr in ("Subject", "From", "To", "Cc", "Date"):
                val = msg.get(hdr)
                if val:
                    headers.append(f"{hdr}: {_decode_header(val)}")

            body = _extract_body(msg, config.max_body_chars)

            output = "\n".join(headers) + "\n\n" + body
            return truncate_output(output, config.max_body_chars)
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

    @toolset.tool
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
                # IMAP LIST format: (\Flags) "delimiter" "folder name"
                # or: (\Flags) "delimiter" folder_name
                # Find the last quoted string, or last space-separated token
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

    if not config.read_only:

        @toolset.tool
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
                reply_to: Message-ID to reply to (sets In-Reply-To and References headers).
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
                    # Strip newlines to prevent header injection
                    safe_reply_to = reply_to.replace("\r", "").replace("\n", "")
                    msg["In-Reply-To"] = safe_reply_to
                    msg["References"] = safe_reply_to

                msg.attach(email.mime.text.MIMEText(body, "plain"))

                recipients = [addr.strip() for addr in to.split(",")]
                if cc:
                    recipients.extend(addr.strip() for addr in cc.split(","))

                if config.smtp_port == 465:
                    server = smtplib.SMTP_SSL(
                        config.smtp_host, config.smtp_port, timeout=config.timeout_seconds
                    )
                else:
                    server = smtplib.SMTP(
                        config.smtp_host, config.smtp_port, timeout=config.timeout_seconds
                    )
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

    return toolset
