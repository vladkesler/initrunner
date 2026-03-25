"""Shared exception for guardrail capabilities."""


class ContentBlockedError(Exception):
    """Raised by guard capabilities when content policy blocks input."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
