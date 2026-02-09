"""Tests for the centralized logging module."""

from __future__ import annotations

import logging

import pytest

from initrunner._log import get_logger, setup_logging


@pytest.fixture()
def _caplog_initrunner(caplog):
    """Attach caplog handler to the ``initrunner`` logger so records are captured
    even though ``propagate=False``."""
    root = logging.getLogger("initrunner")
    root.addHandler(caplog.handler)
    yield
    root.removeHandler(caplog.handler)


class TestGetLogger:
    def test_returns_logger(self):
        log = get_logger("test.tag")
        assert isinstance(log, logging.Logger)
        assert log.name == "initrunner.test.tag"

    def test_child_of_initrunner(self):
        log = get_logger("child")
        assert log.parent is not None
        assert log.parent.name == "initrunner"


class TestSetupLogging:
    def test_idempotent(self):
        root = logging.getLogger("initrunner")
        setup_logging()
        count_before = len(root.handlers)
        setup_logging()
        assert len(root.handlers) == count_before

    def test_propagate_false(self):
        setup_logging()
        root = logging.getLogger("initrunner")
        assert root.propagate is False


class TestLogOutput:
    @pytest.mark.usefixtures("_caplog_initrunner")
    def test_warning_captured(self, caplog):
        log = get_logger("testtag")
        with caplog.at_level("WARNING", logger="initrunner.testtag"):
            log.warning("hello world")
        assert "[testtag] hello world" in caplog.text

    @pytest.mark.usefixtures("_caplog_initrunner")
    def test_debug_suppressed_at_default_level(self, caplog):
        log = get_logger("testtag2")
        with caplog.at_level("WARNING", logger="initrunner.testtag2"):
            log.debug("should not appear")
        assert "should not appear" not in caplog.text

    @pytest.mark.usefixtures("_caplog_initrunner")
    def test_tag_strips_prefix(self, caplog):
        log = get_logger("audit")
        with caplog.at_level("WARNING", logger="initrunner.audit"):
            log.warning("test message")
        assert "[audit] test message" in caplog.text
        assert "[initrunner.audit]" not in caplog.text
