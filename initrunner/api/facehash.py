"""Deterministic face avatar SVG generator.

Port of the facehash algorithm (https://github.com/cossistantcom/cossistant)
to Python.  Same name always produces the same face — no JS needed.
"""

from __future__ import annotations

import html
from functools import lru_cache

from markupsafe import Markup

COLORS = ["#ec4899", "#f59e0b", "#3b82f6", "#f97316", "#10b981"]
FACE_TYPES = ["round", "cross", "line", "curved"]
SPHERE_POSITIONS = [
    (-1, 1),
    (1, 1),
    (1, 0),
    (0, 1),
    (-1, 0),
    (0, 0),
    (0, -1),
    (-1, -1),
    (1, -1),
]

# Rotation degrees per sphere axis unit
_ROT_DEG = 12

# ── Eye SVG data (from upstream faces.tsx) ──────────────────────────

_EYES_ROUND = (
    '<svg aria-hidden="true" fill="none" viewBox="0 0 63 15"'
    ' xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="7.2" cy="7.2" fill="currentColor" r="7.2"/>'
    '<circle cx="55.2" cy="7.2" fill="currentColor" r="7.2"/>'
    "</svg>"
)

_EYES_CROSS = (
    '<svg aria-hidden="true" fill="none" viewBox="0 0 71 23"'
    ' xmlns="http://www.w3.org/2000/svg">'
    '<rect fill="currentColor" height="23" rx="3.5" width="7" x="8" y="0"/>'
    '<rect fill="currentColor" height="7" rx="3.5" width="23" x="0" y="8"/>'
    '<rect fill="currentColor" height="23" rx="3.5" width="7" x="55.2" y="0"/>'
    '<rect fill="currentColor" height="7" rx="3.5" width="23" x="47.3" y="8"/>'
    "</svg>"
)

_EYES_LINE = (
    '<svg aria-hidden="true" fill="none" viewBox="0 0 82 8"'
    ' xmlns="http://www.w3.org/2000/svg">'
    '<rect fill="currentColor" height="6.9" rx="3.5" width="6.9" x="0.07" y="0.16"/>'
    '<rect fill="currentColor" height="6.9" rx="3.5" width="20.7" x="7.9" y="0.16"/>'
    '<rect fill="currentColor" height="6.9" rx="3.5" width="6.9" x="74.7" y="0.16"/>'
    '<rect fill="currentColor" height="6.9" rx="3.5" width="20.7" x="53.1" y="0.16"/>'
    "</svg>"
)

_EYES_CURVED = (
    '<svg aria-hidden="true" fill="none" viewBox="0 0 63 9"'
    ' xmlns="http://www.w3.org/2000/svg">'
    '<path d="M0 5.1c0-.1 0-.2 0-.3.1-.5.3-1 .7-1.3.1 0 .1-.1.2-.1C2.4 2.2'
    " 6 0 10.5 0S18.6 2.2 20.2 3.3c.1 0 .1.1.1.1.4.3.7.9.7 1.3v.3c0 1 0"
    " 1.4 0 1.7-.2 1.3-1.2 1.9-2.5 1.6-.2 0-.7-.3-1.8-.8C15 6.7 12.8 6"
    " 10.5 6s-4.5.7-6.3 1.5c-1 .5-1.5.7-1.8.8-1.3.3-2.3-.3-2.5-1.6v-1.7z"
    '" fill="currentColor"/>'
    '<path d="M42 5.1c0-.1 0-.2 0-.3.1-.5.3-1 .7-1.3.1 0 .1-.1.2-.1C44.4'
    " 2.2 48 0 52.5 0S60.6 2.2 62.2 3.3c.1 0 .1.1.1.1.4.3.7.9.7 1.3v.3c0"
    " 1 0 1.4 0 1.7-.2 1.3-1.2 1.9-2.5 1.6-.2 0-.7-.3-1.8-.8C57 6.7 54.8"
    " 6 52.5 6s-4.5.7-6.3 1.5c-1 .5-1.5.7-1.8.8-1.3.3-2.3-.3-2.5-1.6v-1.7z"
    '" fill="currentColor"/>'
    "</svg>"
)

_EYES = {
    "round": _EYES_ROUND,
    "cross": _EYES_CROSS,
    "line": _EYES_LINE,
    "curved": _EYES_CURVED,
}


def string_hash(s: str) -> int:
    """Deterministic 32-bit hash matching the JS ``(hash << 5) - hash + charCode`` algorithm."""
    h = 0
    for ch in s:
        h = (h << 5) - h + ord(ch)
        h &= 0xFFFFFFFF  # enforce 32-bit unsigned
    return h


@lru_cache(maxsize=256)
def render_facehash_svg(name: str, size: int = 40) -> Markup:
    """Return an inline SVG string for a deterministic face avatar.

    Same *name* always produces the same face.  The mouth shows the
    first letter of the name, uppercased.
    """
    h = string_hash(name)
    face_type = FACE_TYPES[h % len(FACE_TYPES)]
    color = COLORS[h % len(COLORS)]
    rot_x, rot_y = SPHERE_POSITIONS[h % len(SPHERE_POSITIONS)]
    initial = html.escape(name[0].upper()) if name else "?"

    escaped_name = html.escape(name)
    eyes_svg = _EYES[face_type]

    # Rotation angles (CSS custom properties for the wrapper)
    rx_deg = rot_y * _ROT_DEG  # vertical tilt
    ry_deg = rot_x * _ROT_DEG  # horizontal tilt

    r = size // 2  # border-radius for fully rounded

    svg = (
        f'<div class="facehash-wrap" style="--rot-x:{rx_deg}deg;--rot-y:{ry_deg}deg">'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"'
        f' viewBox="0 0 {size} {size}"'
        f' role="img" aria-label="Avatar for {escaped_name}"'
        f' style="color:white;overflow:hidden">'
        # Background
        f'<rect width="{size}" height="{size}" rx="{r}" fill="{color}"/>'
        # Gradient overlay
        f"<defs>"
        f'<radialGradient id="fh-g-{h}" cx="50%" cy="50%" r="50%">'
        f'<stop offset="0%" stop-color="white" stop-opacity="0.15"/>'
        f'<stop offset="60%" stop-color="white" stop-opacity="0"/>'
        f"</radialGradient>"
        f"</defs>"
        f'<rect width="{size}" height="{size}" rx="{r}" fill="url(#fh-g-{h})"/>'
        # Eyes — embedded as a foreignObject so the inner SVG scales nicely
        f'<foreignObject x="{size * 0.1}" y="{size * 0.18}"'
        f' width="{size * 0.8}" height="{size * 0.4}">'
        f'<div xmlns="http://www.w3.org/1999/xhtml" style="display:flex;align-items:center;'
        f'justify-content:center;width:100%;height:100%;color:white">'
        f"{eyes_svg}</div></foreignObject>"
        # Mouth — initial letter
        f'<text x="50%" y="{size * 0.82}" text-anchor="middle"'
        f' font-size="{size * 0.26}" font-weight="bold"'
        f' fill="white" font-family="system-ui,sans-serif">'
        f"{initial}</text>"
        f"</svg></div>"
    )

    return Markup(svg)
