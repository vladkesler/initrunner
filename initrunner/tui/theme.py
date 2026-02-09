"""Reactor Core — custom Textual theme for InitRunner TUI."""

from __future__ import annotations

from textual.theme import Theme

# Named color constants for use in Rich markup across TUI screens
COLOR_PRIMARY = "#d4910a"
COLOR_SUCCESS = "#2ec4b6"
COLOR_SECONDARY = "#5b8fb9"
COLOR_ERROR = "#c0392b"

INITRUNNER_THEME = Theme(
    name="initrunner",
    primary=COLOR_PRIMARY,
    secondary=COLOR_SECONDARY,
    accent=COLOR_PRIMARY,
    success=COLOR_SUCCESS,
    error=COLOR_ERROR,
    warning="#e8a317",
    background="#0d0f12",
    surface="#151a23",
    variables={
        "primary-background": "#1a1510",
    },
)
