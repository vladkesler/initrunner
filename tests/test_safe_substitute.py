"""Tests for safe_substitute -- format string injection prevention."""

from __future__ import annotations

from initrunner._text import safe_substitute


class TestSafeSubstitute:
    def test_basic_substitution(self):
        result = safe_substitute("Process file: {path}", {"path": "/tmp/data.txt"})
        assert result == "Process file: /tmp/data.txt"

    def test_multiple_placeholders(self):
        result = safe_substitute(
            "File {path} changed at {time}", {"path": "/tmp/x", "time": "noon"}
        )
        assert result == "File /tmp/x changed at noon"

    def test_attribute_access_not_triggered(self):
        """Attacker tries {message.__class__} -- must remain as literal text."""
        result = safe_substitute("{message.__class__}", {"message": "test"})
        assert result == "{message.__class__}"

    def test_index_access_not_triggered(self):
        """Attacker tries {message[0]} -- must remain as literal text."""
        result = safe_substitute("{message[0]}", {"message": "test"})
        assert result == "{message[0]}"

    def test_format_spec_not_triggered(self):
        """Attacker tries {message!r} -- must remain as literal text."""
        result = safe_substitute("{message!r}", {"message": "test"})
        assert result == "{message!r}"

    def test_missing_key_left_as_is(self):
        result = safe_substitute("Hello {name} {missing}", {"name": "Bob"})
        assert result == "Hello Bob {missing}"

    def test_empty_values(self):
        result = safe_substitute("No placeholders here", {})
        assert result == "No placeholders here"

    def test_repeated_placeholder(self):
        result = safe_substitute("{x} and {x}", {"x": "val"})
        assert result == "val and val"
