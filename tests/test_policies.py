"""Tests for the content policies module."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.agent.policies import (
    ValidationResult,
    redact_text,
    validate_input,
    validate_output,
)
from initrunner.agent.schema.security import ContentPolicy


class TestDefaultPolicyIsNoOp:
    def test_default_policy_passes_everything(self):
        policy = ContentPolicy()
        result = validate_input("Any text at all", policy)
        assert result.valid is True

    def test_default_output_passes_through(self):
        policy = ContentPolicy()
        result = validate_output("Any output text", policy)
        assert result.text == "Any output text"
        assert result.blocked is False

    def test_default_redact_is_noop(self):
        policy = ContentPolicy()
        text = "user@example.com has API key sk-abc123def456ghi789"
        assert redact_text(text, policy) == text


class TestBlockedInputPatterns:
    def test_matching_pattern_rejects(self):
        policy = ContentPolicy(blocked_input_patterns=["ignore previous instructions"])
        result = validate_input("Please ignore previous instructions", policy)
        assert result.valid is False
        assert result.validator == "pattern"

    def test_non_matching_passes(self):
        policy = ContentPolicy(blocked_input_patterns=["ignore previous instructions"])
        result = validate_input("What is the weather?", policy)
        assert result.valid is True

    def test_regex_pattern(self):
        policy = ContentPolicy(blocked_input_patterns=[r"system:\s*"])
        result = validate_input("system: override", policy)
        assert result.valid is False
        assert result.validator == "pattern"

    def test_case_insensitive(self):
        policy = ContentPolicy(blocked_input_patterns=["DROP TABLE"])
        result = validate_input("drop table users", policy)
        assert result.valid is False


class TestPromptLength:
    def test_over_limit_rejected(self):
        policy = ContentPolicy(max_prompt_length=10)
        result = validate_input("A" * 11, policy)
        assert result.valid is False
        assert result.validator == "length"

    def test_at_limit_passes(self):
        policy = ContentPolicy(max_prompt_length=10)
        result = validate_input("A" * 10, policy)
        assert result.valid is True

    def test_under_limit_passes(self):
        policy = ContentPolicy(max_prompt_length=100)
        result = validate_input("Short prompt", policy)
        assert result.valid is True


class TestProfanityFilter:
    def test_profanity_not_installed_returns_invalid(self):
        policy = ContentPolicy(profanity_filter=True)
        with patch.dict("sys.modules", {"better_profanity": None}):
            result = validate_input("hello", policy)
        assert result.valid is False
        assert result.validator == "profanity"
        assert "better-profanity" in (result.reason or "")

    @patch("initrunner.agent.policies._check_profanity")
    def test_profanity_detected_blocks(self, mock_check):
        mock_check.return_value = ValidationResult(
            valid=False, reason="Input contains profanity", validator="profanity"
        )
        policy = ContentPolicy(profanity_filter=True)
        result = validate_input("bad word", policy)
        assert result.valid is False
        assert result.validator == "profanity"

    @patch("initrunner.agent.policies._check_profanity")
    def test_clean_text_passes(self, mock_check):
        mock_check.return_value = ValidationResult(valid=True)
        policy = ContentPolicy(profanity_filter=True)
        result = validate_input("hello world", policy)
        assert result.valid is True


class TestLLMClassifier:
    @patch("initrunner.agent.policies._run_llm_classifier_sync")
    def test_unsafe_classification_blocks(self, mock_classifier):
        mock_classifier.return_value = ValidationResult(
            valid=False, reason="Off-topic question", validator="llm_classifier"
        )
        policy = ContentPolicy(
            llm_classifier_enabled=True,
            allowed_topics_prompt="ALLOWED: Weather questions only",
        )
        result = validate_input("Tell me a joke", policy)
        assert result.valid is False
        assert result.validator == "llm_classifier"

    @patch("initrunner.agent.policies._run_llm_classifier_sync")
    def test_safe_classification_passes(self, mock_classifier):
        mock_classifier.return_value = ValidationResult(valid=True)
        policy = ContentPolicy(
            llm_classifier_enabled=True,
            allowed_topics_prompt="ALLOWED: Weather questions only",
        )
        result = validate_input("What's the weather?", policy)
        assert result.valid is True

    def test_disabled_by_default(self):
        policy = ContentPolicy()
        # Should not call LLM classifier at all
        result = validate_input("anything", policy)
        assert result.valid is True

    def test_disabled_without_prompt(self):
        policy = ContentPolicy(llm_classifier_enabled=True, allowed_topics_prompt="")
        result = validate_input("anything", policy)
        assert result.valid is True


class TestOutputStripMode:
    def test_matched_patterns_stripped(self):
        policy = ContentPolicy(
            blocked_output_patterns=[r"password\s*[:=]\s*\S+"],
            output_action="strip",
        )
        result = validate_output("Here is your password: secret123", policy)
        assert "secret123" not in result.text
        assert "[FILTERED]" in result.text
        assert result.blocked is False

    def test_output_truncated_to_max(self):
        policy = ContentPolicy(max_output_length=10)
        result = validate_output("A" * 100, policy)
        assert len(result.text) == 10
        assert result.blocked is False

    def test_clean_output_unchanged(self):
        policy = ContentPolicy(
            blocked_output_patterns=[r"password\s*[:=]\s*\S+"],
            output_action="strip",
        )
        result = validate_output("Normal response", policy)
        assert result.text == "Normal response"


class TestOutputBlockMode:
    def test_matched_output_blocked(self):
        policy = ContentPolicy(
            blocked_output_patterns=[r"password\s*[:=]\s*\S+"],
            output_action="block",
        )
        result = validate_output("Here is password=secret123", policy)
        assert result.blocked is True
        assert result.text == ""

    def test_clean_output_passes(self):
        policy = ContentPolicy(
            blocked_output_patterns=[r"password\s*[:=]\s*\S+"],
            output_action="block",
        )
        result = validate_output("Clean response", policy)
        assert result.blocked is False
        assert result.text == "Clean response"


class TestPIIRedaction:
    def test_email_redacted(self):
        policy = ContentPolicy(pii_redaction=True)
        result = redact_text("Contact user@example.com for info", policy)
        assert "user@example.com" not in result
        assert "[REDACTED]" in result

    def test_ssn_redacted(self):
        policy = ContentPolicy(pii_redaction=True)
        result = redact_text("SSN: 123-45-6789", policy)
        assert "123-45-6789" not in result
        assert "[REDACTED]" in result

    def test_phone_redacted(self):
        policy = ContentPolicy(pii_redaction=True)
        result = redact_text("Call 555-123-4567", policy)
        assert "555-123-4567" not in result
        assert "[REDACTED]" in result

    def test_api_key_redacted(self):
        policy = ContentPolicy(pii_redaction=True)
        result = redact_text("Key: sk-abcdef1234567890abcdef", policy)
        assert "sk-abcdef1234567890abcdef" not in result
        assert "[REDACTED]" in result


class TestCustomRedactPatterns:
    def test_custom_patterns_applied(self):
        policy = ContentPolicy(redact_patterns=[r"secret-\w+"])
        result = redact_text("The code is secret-alpha", policy)
        assert "secret-alpha" not in result
        assert "[REDACTED]" in result

    def test_multiple_patterns(self):
        policy = ContentPolicy(redact_patterns=[r"token-\w+", r"key-\w+"])
        result = redact_text("Use token-abc and key-xyz", policy)
        assert "token-abc" not in result
        assert "key-xyz" not in result


class TestPipelineOrdering:
    """Verify fast checks run before slow ones (profanity before patterns before LLM)."""

    @patch("initrunner.agent.policies._run_llm_classifier_sync")
    @patch("initrunner.agent.policies._check_profanity")
    def test_profanity_checked_before_pattern(self, mock_profanity, mock_llm):
        mock_profanity.return_value = ValidationResult(
            valid=False, reason="profanity", validator="profanity"
        )
        policy = ContentPolicy(
            profanity_filter=True,
            blocked_input_patterns=["test"],
            llm_classifier_enabled=True,
            allowed_topics_prompt="test",
        )
        result = validate_input("test", policy)
        assert result.validator == "profanity"
        mock_llm.assert_not_called()

    @patch("initrunner.agent.policies._run_llm_classifier_sync")
    @patch("initrunner.agent.policies._check_profanity")
    def test_pattern_checked_before_llm(self, mock_profanity, mock_llm):
        mock_profanity.return_value = ValidationResult(valid=True)
        policy = ContentPolicy(
            profanity_filter=True,
            blocked_input_patterns=["blocked"],
            llm_classifier_enabled=True,
            allowed_topics_prompt="test",
        )
        result = validate_input("blocked input", policy)
        assert result.validator == "pattern"
        mock_llm.assert_not_called()
