"""Tests for the email tool: schema, toolset builder, tool functions, and helpers."""

from __future__ import annotations

import email
import email.mime.multipart
import email.mime.text
import imaplib
import os
from unittest.mock import MagicMock, patch

import pytest

from initrunner.agent._env import resolve_env_vars
from initrunner.agent.schema.role import AgentSpec
from initrunner.agent.schema.tools import EmailToolConfig
from initrunner.agent.tools._registry import ToolBuildContext
from initrunner.agent.tools.email_tools import (
    _decode_header,
    _extract_body,
    _html_to_markdown,
    build_email_toolset,
)


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


def _make_raw_header(
    from_: str = "sender@example.com",
    subject: str = "Test",
    date: str = "Mon, 1 Jan 2025 00:00:00 +0000",
    message_id: str = "<abc@example.com>",
) -> bytes:
    """Build raw IMAP header bytes."""
    lines = [
        f"From: {from_}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: {message_id}",
        "",
    ]
    return "\r\n".join(lines).encode()


def _make_raw_email(
    subject: str = "Test",
    from_: str = "sender@example.com",
    to: str = "me@example.com",
    body: str = "Hello world",
    content_type: str = "text/plain",
    html_body: str | None = None,
) -> bytes:
    """Build a raw RFC822 email."""
    if html_body is not None:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg.attach(email.mime.text.MIMEText(body, "plain"))
        msg.attach(email.mime.text.MIMEText(html_body, "html"))
    else:
        msg = email.mime.text.MIMEText(body, content_type.split("/")[1])
    msg["Subject"] = subject
    msg["From"] = from_
    msg["To"] = to
    msg["Date"] = "Mon, 1 Jan 2025 00:00:00 +0000"
    msg["Message-ID"] = "<test@example.com>"
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestEmailSchema:
    def test_parses_from_dict(self):
        data = {
            "type": "email",
            "imap_host": "imap.gmail.com",
            "username": "user@gmail.com",
            "password": "secret",
        }
        config = EmailToolConfig.model_validate(data)
        assert config.imap_host == "imap.gmail.com"
        assert config.username == "user@gmail.com"
        assert config.read_only is True

    def test_defaults(self):
        config = EmailToolConfig(
            imap_host="imap.example.com",
            username="user",
            password="pass",
        )
        assert config.imap_port == 993
        assert config.smtp_port == 587
        assert config.use_ssl is True
        assert config.default_folder == "INBOX"
        assert config.max_results == 20
        assert config.max_body_chars == 50_000
        assert config.timeout_seconds == 30

    def test_summary(self):
        config = EmailToolConfig(
            imap_host="imap.gmail.com",
            username="user",
            password="pass",
        )
        s = config.summary()
        assert "email:" in s
        assert "imap.gmail.com" in s
        assert "ro=True" in s

    def test_summary_read_only_false(self):
        config = EmailToolConfig(
            imap_host="imap.gmail.com",
            smtp_host="smtp.gmail.com",
            username="user",
            password="pass",
            read_only=False,
        )
        assert "ro=False" in config.summary()

    def test_required_fields(self):
        with pytest.raises(ValueError):
            EmailToolConfig.model_validate({"type": "email"})

    def test_smtp_host_required_when_not_read_only(self):
        with pytest.raises(ValueError, match="smtp_host is required"):
            EmailToolConfig(
                imap_host="imap.example.com",
                username="user",
                password="pass",
                read_only=False,
            )

    def test_smtp_host_not_required_when_read_only(self):
        config = EmailToolConfig(
            imap_host="imap.example.com",
            username="user",
            password="pass",
            read_only=True,
        )
        assert config.smtp_host == ""

    def test_in_agent_spec(self):
        spec_data = {
            "role": "Test agent",
            "model": {"provider": "openai", "name": "gpt-4o-mini"},
            "tools": [
                {
                    "type": "email",
                    "imap_host": "imap.gmail.com",
                    "username": "${EMAIL_USER}",
                    "password": "${EMAIL_PASS}",
                }
            ],
        }
        spec = AgentSpec.model_validate(spec_data)
        assert len(spec.tools) == 1
        assert isinstance(spec.tools[0], EmailToolConfig)


# ---------------------------------------------------------------------------
# Toolset builder tests
# ---------------------------------------------------------------------------


class TestEmailToolset:
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_read_only_excludes_send(self, _mock_imap):
        config = EmailToolConfig(
            imap_host="imap.example.com",
            username="user",
            password="pass",
            read_only=True,
        )
        toolset = build_email_toolset(config, _make_ctx())
        assert "search_inbox" in toolset.tools
        assert "read_email" in toolset.tools
        assert "list_folders" in toolset.tools
        assert "send_email" not in toolset.tools

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_read_only_false_includes_send(self, _mock_imap):
        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        assert "send_email" in toolset.tools

    def test_env_var_resolution(self):
        os.environ["TEST_EMAIL_USER"] = "resolved_user"
        os.environ["TEST_EMAIL_PASS"] = "resolved_pass"
        try:
            config = EmailToolConfig(
                imap_host="imap.example.com",
                username="${TEST_EMAIL_USER}",
                password="${TEST_EMAIL_PASS}",
            )
            assert resolve_env_vars(config.username) == "resolved_user"
            assert resolve_env_vars(config.password) == "resolved_pass"
        finally:
            os.environ.pop("TEST_EMAIL_USER")
            os.environ.pop("TEST_EMAIL_PASS")


# ---------------------------------------------------------------------------
# search_inbox tests
# ---------------------------------------------------------------------------


class TestSearchInbox:
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_search_all(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"5"])
        mock_conn.search.return_value = ("OK", [b"1 2 3"])

        raw_header = _make_raw_header()
        mock_conn.fetch.return_value = ("OK", [(b"1 (BODY[HEADER.FIELDS ...] {100}", raw_header)])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        assert "From:" in result
        assert "Subject:" in result
        mock_conn.select.assert_called_with("INBOX", readonly=True)

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_custom_folder(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = ("OK", [(b"1 (BODY ...)", _make_raw_header())])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        fn(folder="Sent")
        mock_conn.select.assert_called_with("Sent", readonly=True)

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_limit(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"10"])
        mock_conn.search.return_value = ("OK", [b"1 2 3 4 5 6 7 8 9 10"])

        raw = _make_raw_header()
        mock_conn.fetch.return_value = ("OK", [(b"1 (BODY ...)", raw)])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        fn(limit=2)
        # fetch should be called exactly 2 times (limited)
        assert mock_conn.fetch.call_count == 2

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_no_results(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"0"])
        mock_conn.search.return_value = ("OK", [b""])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        assert "No messages found" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_newest_first_ordering(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"3"])
        mock_conn.search.return_value = ("OK", [b"1 2 3"])

        headers = {
            b"3": _make_raw_header(subject="Third"),
            b"2": _make_raw_header(subject="Second"),
            b"1": _make_raw_header(subject="First"),
        }

        def mock_fetch(num, _spec):
            return ("OK", [(b"data", headers.get(num, _make_raw_header()))])

        mock_conn.fetch.side_effect = mock_fetch

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        # Third should appear before Second, which appears before First
        pos_third = result.index("Third")
        pos_second = result.index("Second")
        pos_first = result.index("First")
        assert pos_third < pos_second < pos_first

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_connection_error(self, mock_imap_cls):
        mock_imap_cls.side_effect = OSError("Connection refused")

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        assert "IMAP connection error" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_imap_error(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.side_effect = imaplib.IMAP4.error("Login failed")

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        assert "IMAP error" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_uses_body_peek(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = ("OK", [(b"data", _make_raw_header())])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        fn()
        fetch_call = mock_conn.fetch.call_args
        assert "BODY.PEEK" in fetch_call[0][1]

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_truncation(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])

        long_subject = "A" * 60_000
        mock_conn.fetch.return_value = ("OK", [(b"data", _make_raw_header(subject=long_subject))])

        config = EmailToolConfig(
            imap_host="imap.example.com",
            username="user",
            password="pass",
            max_body_chars=100,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["search_inbox"].function

        result = fn()
        assert len(result) <= 100 + len("\n[truncated]")


# ---------------------------------------------------------------------------
# read_email tests
# ---------------------------------------------------------------------------


class TestReadEmail:
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_plain_text(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = (
            "OK",
            [(b"1 (RFC822 {500}", _make_raw_email(body="Hello world"))],
        )

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<test@example.com>")
        assert "Hello world" in result
        assert "Subject: Test" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_html_to_markdown(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])

        # Build HTML-only email (no plain text part)
        html_msg = email.mime.text.MIMEText("<p>Hello <b>bold</b></p>", "html")
        html_msg["Subject"] = "Test"
        html_msg["From"] = "sender@example.com"
        html_msg["To"] = "me@example.com"
        html_msg["Date"] = "Mon, 1 Jan 2025 00:00:00 +0000"
        html_msg["Message-ID"] = "<test@example.com>"
        html_raw = html_msg.as_bytes()
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {500}", html_raw)])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<test@example.com>")
        # Should contain some representation of the HTML content
        assert "Hello" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_multipart_prefers_plain(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])

        raw = _make_raw_email(body="Plain text body", html_body="<p>HTML body</p>")
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {500}", raw)])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<test@example.com>")
        assert "Plain text body" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_not_found(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"0"])
        mock_conn.search.return_value = ("OK", [b""])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<nonexistent@example.com>")
        assert "not found" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_decoded_headers(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])

        # RFC 2047 encoded subject
        raw = _make_raw_email(subject="=?utf-8?B?SGVsbG8gV29ybGQ=?=", body="content")
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {500}", raw)])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<test@example.com>")
        assert "Hello World" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_truncation(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])

        long_body = "X" * 60_000
        raw = _make_raw_email(body=long_body)
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {500}", raw)])

        config = EmailToolConfig(
            imap_host="imap.example.com",
            username="user",
            password="pass",
            max_body_chars=200,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        result = fn(message_id="<test@example.com>")
        assert len(result) <= 200 + len("\n[truncated]")

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_marks_as_seen(self, mock_imap_cls):
        """read_email uses RFC822 (not BODY.PEEK) so messages are marked as \\Seen."""
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = (
            "OK",
            [(b"1 (RFC822 {500}", _make_raw_email())],
        )

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["read_email"].function

        fn(message_id="<test@example.com>")
        # select is called with readonly=False so \Seen flag can be set
        mock_conn.select.assert_called_with("INBOX", readonly=False)
        # fetch uses RFC822 (which sets \Seen), not BODY.PEEK
        fetch_call = mock_conn.fetch.call_args
        assert "RFC822" in fetch_call[0][1]


# ---------------------------------------------------------------------------
# list_folders tests
# ---------------------------------------------------------------------------


class TestListFolders:
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_normal_listing(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.list.return_value = (
            "OK",
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Sent"',
                b'(\\HasNoChildren) "/" "Drafts"',
            ],
        )

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["list_folders"].function

        result = fn()
        assert "Drafts" in result
        assert "INBOX" in result
        assert "Sent" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_empty_result(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [])
        mock_conn.list.return_value = ("OK", [])

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["list_folders"].function

        result = fn()
        assert "no folders found" in result

    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_connection_error(self, mock_imap_cls):
        mock_imap_cls.side_effect = OSError("Connection refused")

        config = EmailToolConfig(imap_host="imap.example.com", username="user", password="pass")
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["list_folders"].function

        result = fn()
        assert "IMAP connection error" in result


# ---------------------------------------------------------------------------
# send_email tests
# ---------------------------------------------------------------------------


class TestSendEmail:
    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_simple_send(self, _mock_imap, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        result = fn(to="recipient@example.com", subject="Test", body="Hello")
        assert "Email sent to recipient@example.com" in result
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "pass")
        mock_server.sendmail.assert_called_once()

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_reply_to_headers(self, _mock_imap, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        fn(
            to="recipient@example.com",
            subject="Re: Test",
            body="Reply",
            reply_to="<original@example.com>",
        )

        sent_msg_str = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(sent_msg_str)
        assert msg["In-Reply-To"] == "<original@example.com>"
        assert msg["References"] == "<original@example.com>"

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_cc_recipients(self, _mock_imap, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        result = fn(
            to="to@example.com",
            subject="Test",
            body="Hello",
            cc="cc1@example.com, cc2@example.com",
        )
        assert "cc:" in result

        recipients = mock_server.sendmail.call_args[0][1]
        assert "to@example.com" in recipients
        assert "cc1@example.com" in recipients
        assert "cc2@example.com" in recipients

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_smtp_error(self, _mock_imap, mock_smtp_cls):
        import smtplib

        mock_smtp_cls.return_value.__enter__ = MagicMock()
        mock_smtp_cls.side_effect = smtplib.SMTPException("Auth failed")

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        result = fn(to="to@example.com", subject="Test", body="Hello")
        assert "SMTP error" in result

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP_SSL")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_ssl_for_port_465(self, _mock_imap, mock_smtp_ssl_cls):
        mock_server = MagicMock()
        mock_smtp_ssl_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            smtp_port=465,
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        fn(to="to@example.com", subject="Test", body="Hello")
        mock_smtp_ssl_cls.assert_called_once()
        # starttls should NOT be called for SMTP_SSL
        mock_server.starttls.assert_not_called()

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_starttls_for_port_587(self, _mock_imap, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        fn(to="to@example.com", subject="Test", body="Hello")
        mock_server.starttls.assert_called_once()

    @patch("initrunner.agent.tools.email_tools.smtplib.SMTP")
    @patch("initrunner.agent.tools.email_tools.imaplib.IMAP4_SSL")
    def test_header_injection_prevention(self, _mock_imap, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = EmailToolConfig(
            imap_host="imap.example.com",
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass",
            read_only=False,
        )
        toolset = build_email_toolset(config, _make_ctx())
        fn = toolset.tools["send_email"].function

        fn(
            to="to@example.com",
            subject="Test",
            body="Hello",
            reply_to="<legit@example.com>\r\nBcc: evil@example.com",
        )

        sent_msg_str = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(sent_msg_str)
        # Newlines stripped, so no Bcc injection
        assert msg["In-Reply-To"] == "<legit@example.com>Bcc: evil@example.com"
        assert "\r" not in (msg["In-Reply-To"] or "")
        assert "\n" not in (msg["In-Reply-To"] or "")


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestEmailHelpers:
    def test_decode_header_plain(self):
        assert _decode_header("Hello World") == "Hello World"

    def test_decode_header_rfc2047(self):
        encoded = "=?utf-8?B?SGVsbG8gV29ybGQ=?="
        assert _decode_header(encoded) == "Hello World"

    def test_decode_header_latin1(self):
        encoded = "=?iso-8859-1?Q?Caf=E9?="
        result = _decode_header(encoded)
        assert "Caf" in result

    def test_extract_body_plain(self):
        msg = email.mime.text.MIMEText("Plain body", "plain")
        result = _extract_body(msg)
        assert result == "Plain body"

    def test_extract_body_html(self):
        msg = email.mime.text.MIMEText("<p>HTML body</p>", "html")
        result = _extract_body(msg)
        assert "HTML body" in result

    def test_extract_body_multipart_prefers_plain(self):
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg.attach(email.mime.text.MIMEText("Plain text", "plain"))
        msg.attach(email.mime.text.MIMEText("<p>HTML</p>", "html"))
        result = _extract_body(msg)
        assert "Plain text" in result
        # Should NOT contain raw HTML tags
        assert "<p>" not in result

    def test_extract_body_latin1_fallback(self):
        """Test that latin-1 fallback works for decode errors."""
        # Manually set a charset that will fail for certain bytes
        raw_bytes = b"Caf\xe9 au lait"
        part = MagicMock()
        part.get_content_type.return_value = "text/plain"
        part.get_payload.return_value = raw_bytes
        part.get_content_charset.return_value = "utf-8"
        part.get.return_value = ""
        part.is_multipart.return_value = False

        result = _extract_body(part)
        assert "Caf" in result

    def test_extract_body_no_content(self):
        msg = email.mime.multipart.MIMEMultipart("mixed")
        # Multipart with no text parts
        result = _extract_body(msg)
        assert "no text content" in result

    def test_html_to_markdown_with_markdownify(self):
        html = "<p>Hello <b>bold</b></p>"
        result = _html_to_markdown(html)
        assert "Hello" in result
        assert "bold" in result

    def test_html_to_markdown_strips_script(self):
        html = "<p>Content</p><script>alert('xss')</script>"
        result = _html_to_markdown(html)
        assert "Content" in result
        assert "alert" not in result

    @patch.dict("sys.modules", {"markdownify": None})
    def test_html_to_markdown_fallback_without_markdownify(self):
        """When markdownify is not available, falls back to BeautifulSoup.get_text()."""
        import sys

        # Save and remove markdownify
        saved = sys.modules.get("markdownify")
        sys.modules["markdownify"] = None  # type: ignore[assignment]
        try:
            # Force re-import to trigger the fallback path
            html = "<p>Fallback content</p>"
            result = _html_to_markdown(html)
            assert "Fallback content" in result
        finally:
            if saved is not None:
                sys.modules["markdownify"] = saved
            else:
                sys.modules.pop("markdownify", None)
