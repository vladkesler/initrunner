"""Self-contained login page for dashboard authentication."""

from __future__ import annotations

import html


def render_login_page(*, error: str | None = None, next_path: str = "/") -> str:
    """Return a complete HTML login page.

    Styled to match the Electric Charcoal design system so the transition
    into the SvelteKit SPA feels seamless.
    """
    error_block = ""
    if error:
        escaped = html.escape(error)
        error_block = (
            f'<div style="color:#ff4d6a;font-size:13px;margin-bottom:16px">{escaped}</div>'
        )

    next_val = html.escape(next_path, quote=True)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login - InitRunner Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{
    font-family:'Space Grotesk',system-ui,sans-serif;
    background:#0e0e10;color:#f0f0f0;
    display:flex;align-items:center;justify-content:center;
    min-height:100vh;
  }}
  .card{{
    background:#161618;border:1px solid #2a2a30;
    border-top-color:rgba(200,255,0,0.15);
    padding:40px;width:100%;max-width:380px;
  }}
  h1{{
    font-size:20px;font-weight:600;letter-spacing:-0.02em;
    margin-bottom:4px;
  }}
  .subtitle{{
    font-family:'IBM Plex Mono',monospace;font-size:12px;
    color:#70707c;text-transform:uppercase;letter-spacing:0.1em;
    margin-bottom:32px;
  }}
  label{{
    display:block;font-family:'IBM Plex Mono',monospace;
    font-size:12px;font-weight:500;color:#70707c;
    text-transform:uppercase;letter-spacing:0.1em;
    margin-bottom:8px;
  }}
  input[type="password"]{{
    width:100%;padding:10px 12px;
    background:#0e0e10;border:1px solid #2a2a30;
    color:#f0f0f0;font-family:'Space Grotesk',system-ui,sans-serif;
    font-size:14px;outline:none;
    transition:border-color 150ms,box-shadow 150ms;
  }}
  input[type="password"]:focus{{
    border-color:rgba(200,255,0,0.4);
    box-shadow:0 0 0 3px rgba(200,255,0,0.08);
  }}
  button{{
    width:100%;margin-top:20px;padding:10px 24px;
    background:#c8ff00;color:#0e0e10;
    border:none;border-radius:9999px;cursor:pointer;
    font-family:'Space Grotesk',system-ui,sans-serif;
    font-size:14px;font-weight:500;
    transition:background-color 150ms;
  }}
  button:hover{{background:#d4ff33}}
  button:active{{background:#b8ef00}}
</style>
</head>
<body>
<div class="card">
  <h1>InitRunner</h1>
  <div class="subtitle">Dashboard</div>
  {error_block}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{next_val}">
    <label for="api_key">API Key</label>
    <input type="password" id="api_key" name="api_key" autofocus required>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""
