"""Secret scrubbing for audit log entries."""

from __future__ import annotations

import re

_PATTERNS = [
    r"gh[pousr]_[A-Za-z0-9_]{36,}",  # GitHub classic tokens
    r"github_pat_[A-Za-z0-9_]{22,}",  # GitHub fine-grained PATs
    r"xox[bpars]-[A-Za-z0-9-]{10,}",  # Slack tokens
    r"AKIA[0-9A-Z]{16}",  # AWS access key IDs
    r"sk-ant-[A-Za-z0-9_-]{20,}",  # Anthropic keys
    r"sk-proj-[A-Za-z0-9_-]{20,}",  # OpenAI project keys
    r"sk-[A-Za-z0-9_-]{20,}",  # OpenAI keys (general)
    r"[sr]k_live_[A-Za-z0-9]{20,}",  # Stripe live keys
    r"[sr]k_test_[A-Za-z0-9]{20,}",  # Stripe test keys
    r"pk_(?:live|test)_[A-Za-z0-9]{20,}",  # Stripe publishable
    r"rk_(?:live|test)_[A-Za-z0-9]{20,}",  # Stripe restricted
    r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}",  # SendGrid
    r"SK[a-f0-9]{32}",  # Twilio
    r"Bearer\s+[A-Za-z0-9_\-.]{20,}",  # Bearer tokens
]

_COMBINED_RE = re.compile("|".join(_PATTERNS))


def scrub_secrets(text: str) -> str:
    """Replace known secret patterns with ``[REDACTED]``."""
    if not text:
        return text
    return _COMBINED_RE.sub("[REDACTED]", text)
