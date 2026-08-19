"""Tests for the centralized logging module."""

from __future__ import annotations

import logging

import pytest

from initrunner._log import _PROVIDER_LOGGERS, _resolve_level, get_logger, setup_logging


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


class TestLogLevelEnv:
    """``INITRUNNER_LOG_LEVEL`` selects the level when ``--verbose`` is absent."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("DEBUG", logging.DEBUG),
            ("debug", logging.DEBUG),
            ("INFO", logging.INFO),
            ("10", logging.DEBUG),
            ("", logging.WARNING),
            ("TRACE", logging.WARNING),
        ],
    )
    def test_resolve_level_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("INITRUNNER_LOG_LEVEL", raw)
        level, _ = _resolve_level(verbose=False)
        assert level == expected

    def test_unset_env_is_warning(self, monkeypatch):
        monkeypatch.delenv("INITRUNNER_LOG_LEVEL", raising=False)
        assert _resolve_level(verbose=False) == (logging.WARNING, None)

    def test_verbose_beats_env(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_LOG_LEVEL", "ERROR")
        assert _resolve_level(verbose=True) == (logging.DEBUG, None)

    def test_invalid_env_is_reported(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_LOG_LEVEL", "LOUD")
        assert _resolve_level(verbose=False) == (logging.WARNING, "LOUD")


class TestProviderLoggers:
    """At DEBUG the provider HTTP loggers share the InitRunner handler."""

    def test_provider_loggers_raised_at_debug(self, monkeypatch):
        monkeypatch.setattr("initrunner._log._setup_done", False)
        monkeypatch.setenv("INITRUNNER_LOG_LEVEL", "DEBUG")
        saved = {
            name: (
                logging.getLogger(name).level,
                list(logging.getLogger(name).handlers),
                logging.getLogger(name).propagate,
            )
            for name in _PROVIDER_LOGGERS
        }
        initrunner_saved = list(logging.getLogger("initrunner").handlers)
        try:
            setup_logging()
            for name in _PROVIDER_LOGGERS:
                provider = logging.getLogger(name)
                assert provider.level == logging.DEBUG
                assert provider.handlers
                assert provider.propagate is False
        finally:
            for name, (level, handlers, propagate) in saved.items():
                provider = logging.getLogger(name)
                provider.setLevel(level)
                provider.handlers = handlers
                provider.propagate = propagate
            logging.getLogger("initrunner").handlers = initrunner_saved

    def test_provider_loggers_untouched_at_default_level(self, monkeypatch):
        monkeypatch.setattr("initrunner._log._setup_done", False)
        monkeypatch.delenv("INITRUNNER_LOG_LEVEL", raising=False)
        httpx_logger = logging.getLogger("httpx")
        before = list(httpx_logger.handlers)
        initrunner_saved = list(logging.getLogger("initrunner").handlers)
        try:
            setup_logging()
            assert list(httpx_logger.handlers) == before
        finally:
            logging.getLogger("initrunner").handlers = initrunner_saved
