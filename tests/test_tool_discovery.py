"""Tests for tool discovery retry behaviour."""

from __future__ import annotations

import importlib
import logging
from unittest.mock import patch

from initrunner.agent.tools._registry import (
    _discovered_modules,
    _ensure_discovered,
    _reset_discovery,
)

_PATCH_TARGET = "initrunner.agent.tools._registry.importlib.import_module"


class TestToolDiscovery:
    def setup_method(self):
        _reset_discovery()

    def teardown_method(self):
        _reset_discovery()
        # Re-run normal discovery so subsequent tests are unaffected
        _ensure_discovered()

    def test_successful_discovery_sets_all_discovered(self):
        """When all modules import successfully, _all_discovered becomes True."""
        _ensure_discovered()
        from initrunner.agent.tools import _registry

        assert _registry._all_discovered is True

    def test_failed_import_leaves_all_discovered_false(self):
        """A failing module should leave _all_discovered False so retries happen."""
        original_import = importlib.import_module

        def _failing_import(name, *args, **kwargs):
            if name == "initrunner.mcp.server":
                raise ImportError("synthetic failure")
            return original_import(name, *args, **kwargs)

        with patch(_PATCH_TARGET, side_effect=_failing_import):
            _ensure_discovered()

        from initrunner.agent.tools import _registry

        assert _registry._all_discovered is False
        assert "initrunner.mcp.server" not in _discovered_modules

    def test_retry_succeeds_after_fix(self):
        """After a failed import is fixed, the next call discovers it."""
        original_import = importlib.import_module
        fail = True

        def _conditional_import(name, *args, **kwargs):
            if name == "initrunner.mcp.server" and fail:
                raise ImportError("synthetic failure")
            return original_import(name, *args, **kwargs)

        with patch(_PATCH_TARGET, side_effect=_conditional_import):
            _ensure_discovered()

        from initrunner.agent.tools import _registry

        assert _registry._all_discovered is False
        assert "initrunner.mcp.server" not in _discovered_modules

        # "Fix" the import and retry
        fail = False
        _ensure_discovered()

        assert _registry._all_discovered is True
        assert "initrunner.mcp.server" in _discovered_modules

    def test_failed_import_logs_at_error(self, caplog):
        """Failed imports should log at ERROR level, not WARNING."""
        original_import = importlib.import_module

        def _failing_import(name, *args, **kwargs):
            if name == "initrunner.mcp.server":
                raise ImportError("synthetic failure")
            return original_import(name, *args, **kwargs)

        ir_logger = logging.getLogger("initrunner")
        ir_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.ERROR):
                with patch(_PATCH_TARGET, side_effect=_failing_import):
                    _ensure_discovered()
            assert "Failed to import tool module" in caplog.text
            assert "initrunner.mcp.server" in caplog.text
        finally:
            ir_logger.removeHandler(caplog.handler)
