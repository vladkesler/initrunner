# Facehash Avatars

Facehash avatars are deterministic, server-rendered SVG faces used as visual
identifiers for roles throughout the dashboard. The same role name always
produces the same face — no external avatar service or user-uploaded images
needed. Avatars appear in the roles table, role detail header, chat messages,
and audit log rows.

## Algorithm

The generator lives in `initrunner/api/facehash.py` and is a Python port of
the [cossistant/facehash](https://github.com/cossistantcom/cossistant) JS
library. Given a name string, it:

1. Computes a deterministic 32-bit hash using the JS-compatible
   `(hash << 5) - hash + charCode` algorithm (`string_hash()`).
2. Selects visual attributes from the hash:

| Attribute | Source | Options |
|-----------|--------|---------|
| Face type (eye style) | `hash % 4` | `round`, `cross`, `line`, `curved` |
| Background color | `hash % 5` | `#ec4899`, `#f59e0b`, `#3b82f6`, `#f97316`, `#10b981` |
| Sphere position (3D tilt) | `hash % 9` | 9 `(x, y)` pairs from `SPHERE_POSITIONS` |
| Mouth letter | — | First character of the name, uppercased |

3. Builds an inline SVG containing: a colored rounded rect, a radial gradient
   overlay, eye shapes via `<foreignObject>`, and a `<text>` initial.
4. Wraps the SVG in a `<div class="facehash-wrap">` with CSS custom properties
   `--rot-x` and `--rot-y` (multiples of 12 deg) for the 3D tilt effect.

## API

```python
from initrunner.api.facehash import render_facehash_svg

svg = render_facehash_svg("my-role", size=40)  # returns markupsafe.Markup
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | *(required)* | Name to hash — same name always gives the same face |
| `size` | `int` | `40` | Width and height of the SVG in pixels |

Returns a `markupsafe.Markup` string (safe for direct insertion into HTML).
Results are cached with `@lru_cache(maxsize=256)`.

## Jinja2 Integration

`create_dashboard_app()` in `initrunner/api/app.py` registers the function as a
Jinja2 global:

```python
env.globals["facehash"] = render_facehash_svg
```

Templates call it directly:

```html
{{ facehash(role.name, 32) }}
{{ facehash(r.agent_name, 24) }}
```

## 3D Tilt Effect

The wrapper `<div>` carries CSS custom properties that drive a `perspective` +
`rotateX/rotateY` transform. On hover the rotation resets to `0deg`, creating a
"snap to front" interaction.

```css
.facehash-wrap {
    perspective: 600px;
    display: inline-flex;
    flex-shrink: 0;
}
.facehash-wrap > svg {
    transform: rotateX(var(--rot-x, 0deg)) rotateY(var(--rot-y, 0deg));
    transition: transform 0.3s ease;
}
.facehash-wrap:hover > svg {
    transform: rotateX(0deg) rotateY(0deg);
}
```

These styles live in `initrunner/_static/style.css`.

## Chat Streaming

During SSE streaming, new assistant messages are built client-side by
JavaScript. The chat page passes the server-rendered avatar to JS via a hidden
`<template>` element:

```html
<template id="assistant-avatar">{{ facehash(role_name, 32) }}</template>
```

`app.js` reads it with `getAssistantAvatarHtml()` and injects the SVG into each
new assistant chat bubble, keeping avatars consistent between server-rendered
history and streamed messages.

## Where Avatars Appear

| Location | Template | Size |
|----------|----------|------|
| Roles table | `roles/_table.html` | 32 px |
| Role detail header | `roles/detail.html` | 48 px |
| Chat messages (history + streamed) | `chat/page.html`, `chat/_message.html` | 32 px |
| Audit log rows | `audit/_table.html` | 24 px |

## Security

- **XSS prevention** — the `name` parameter is escaped with `html.escape()`
  before insertion into the SVG. Both the `aria-label` attribute and the mouth
  initial are escaped.
- **Markup return type** — the function returns `markupsafe.Markup`, which
  Jinja2 treats as pre-escaped and inserts without double-escaping. This is safe
  because the SVG is constructed from escaped inputs and static strings.

## Testing

`tests/test_facehash.py` covers:

| Test class | Coverage |
|------------|----------|
| `TestStringHash` | Determinism, distinct outputs, empty string, 32-bit overflow |
| `TestRenderFacehashSvg` | Markup return type, SVG structure, eye elements, initial letter, size parameter, accessibility attributes (`role="img"`, `aria-label`), XSS safety, LRU cache hits, gradient presence, 3D rotation CSS vars, wrapper class |

Run the tests:

```bash
uv run pytest tests/test_facehash.py -v
```
