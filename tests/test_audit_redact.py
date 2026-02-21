"""Unit tests for audit secret scrubbing patterns."""

from __future__ import annotations

from initrunner.audit._redact import scrub_secrets


class TestGitHubTokens:
    def test_classic_ghp_token(self):
        text = "token: ghp_ABCDEFghijklmnopqrstuvwxyz0123456789ab"
        result = scrub_secrets(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_classic_gho_token(self):
        text = "gho_ABCDEFghijklmnopqrstuvwxyz0123456789ab"
        result = scrub_secrets(text)
        assert "gho_" not in result
        assert "[REDACTED]" in result

    def test_fine_grained_pat(self):
        text = "github_pat_ABCDEFGHIJKLMNOPQRSTUV0123456789abcdef"
        result = scrub_secrets(text)
        assert "github_pat_" not in result
        assert "[REDACTED]" in result


class TestSlackTokens:
    def test_xoxb_token(self):
        text = "SLACK_TOKEN=xoxb-1234567890-abcdefghij"
        result = scrub_secrets(text)
        assert "xoxb-" not in result
        assert "[REDACTED]" in result

    def test_xoxp_token(self):
        text = "xoxp-1234567890-abcdefghij"
        result = scrub_secrets(text)
        assert "xoxp-" not in result
        assert "[REDACTED]" in result


class TestAWSKeys:
    def test_aws_access_key_id(self):
        text = "key: AKIAIOSFODNN7EXAMPLE"
        result = scrub_secrets(text)
        assert "AKIA" not in result
        assert "[REDACTED]" in result


class TestAnthropicKeys:
    def test_sk_ant_key(self):
        text = "sk-ant-api03-abcdefghijklmnopqrst"
        result = scrub_secrets(text)
        assert "sk-ant-" not in result
        assert "[REDACTED]" in result


class TestOpenAIKeys:
    def test_sk_key(self):
        text = "sk-abcdefghijklmnopqrstuvwx"
        result = scrub_secrets(text)
        assert "sk-" not in result
        assert "[REDACTED]" in result

    def test_sk_proj_key(self):
        text = "sk-proj-abcdefghijklmnopqrstuvwx"
        result = scrub_secrets(text)
        assert "sk-proj-" not in result
        assert "[REDACTED]" in result


class TestStripeKeys:
    def test_sk_live(self):
        text = "sk_live_ABCDEFghijklmnopqrstuv"
        result = scrub_secrets(text)
        assert "sk_live_" not in result
        assert "[REDACTED]" in result

    def test_sk_test(self):
        text = "sk_test_ABCDEFghijklmnopqrstuv"
        result = scrub_secrets(text)
        assert "sk_test_" not in result
        assert "[REDACTED]" in result

    def test_pk_live(self):
        text = "pk_live_ABCDEFghijklmnopqrstuv"
        result = scrub_secrets(text)
        assert "pk_live_" not in result
        assert "[REDACTED]" in result

    def test_rk_test(self):
        text = "rk_test_ABCDEFghijklmnopqrstuv"
        result = scrub_secrets(text)
        assert "rk_test_" not in result
        assert "[REDACTED]" in result


class TestSendGrid:
    def test_sendgrid_key(self):
        text = "SG.abcdefghijklmnopqrstuv.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrst"
        result = scrub_secrets(text)
        assert "SG." not in result
        assert "[REDACTED]" in result


class TestTwilio:
    def test_twilio_key(self):
        text = "SK0123456789abcdef0123456789abcdef"
        result = scrub_secrets(text)
        assert "SK0123" not in result
        assert "[REDACTED]" in result


class TestBearerTokens:
    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload"
        result = scrub_secrets(text)
        assert "eyJhbGci" not in result
        assert "[REDACTED]" in result


class TestTelegramTokens:
    def test_telegram_bot_token(self):
        text = "token: 123456789:ABCDefGhIJKlmnOPQRSTuvwxyz123456789"
        result = scrub_secrets(text)
        assert "123456789:" not in result
        assert "[REDACTED]" in result
        assert result == "token: [REDACTED]"

    def test_surrounding_text_preserved(self):
        text = "before 987654321:ABCDefGhIJKlmnOPQRSTuvwxyz123456789 after"
        result = scrub_secrets(text)
        assert result == "before [REDACTED] after"


class TestDiscordTokens:
    def test_discord_bot_token(self):
        text = "token: FAKE_TOKEN_aaaBBBcccDDD11.G1a2b3.xyzXYZ-fake_test_0123456789a"
        result = scrub_secrets(text)
        assert "FAKE_TOKEN" not in result
        assert "[REDACTED]" in result
        assert result == "token: [REDACTED]"

    def test_surrounding_text_preserved(self):
        text = "before FAKE_TOKEN_aaaBBBcccDDD11.G1a2b3.xyzXYZ-fake_test_0123456789a after"
        result = scrub_secrets(text)
        assert result == "before [REDACTED] after"


class TestEdgeCases:
    def test_empty_string(self):
        assert scrub_secrets("") == ""

    def test_normal_text_preserved(self):
        text = "Hello, this is a normal log message with no secrets."
        assert scrub_secrets(text) == text

    def test_multiple_secrets_all_scrubbed(self):
        text = (
            "key1=sk-abcdefghijklmnopqrstuvwx "
            "key2=ghp_ABCDEFghijklmnopqrstuvwxyz0123456789ab "
            "key3=xoxb-1234567890-abcdefghij"
        )
        result = scrub_secrets(text)
        assert "sk-" not in result
        assert "ghp_" not in result
        assert "xoxb-" not in result
        assert result.count("[REDACTED]") == 3

    def test_code_example_not_over_redacted(self):
        text = 'export MY_VAR="short_value"'
        assert scrub_secrets(text) == text

    def test_short_sk_prefix_not_matched(self):
        """sk- followed by fewer than 20 chars should not match."""
        text = "sk-short"
        assert scrub_secrets(text) == text
