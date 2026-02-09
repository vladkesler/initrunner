# Dashboard Authentication

The `initrunner ui` command includes built-in authentication that protects all
dashboard API endpoints. A Bearer token is auto-generated on first launch,
persisted across restarts, and passed to the browser automatically.

## Quick Start

```bash
initrunner ui
```

On startup the CLI prints the active API key and opens the browser with the
token embedded in the URL:

```
Starting dashboard API at http://127.0.0.1:8420
API docs at http://127.0.0.1:8420/api/docs
API key: <generated-key>
The browser will open with the key in the URL.
```

No configuration is needed for local development — a key is generated and
persisted automatically.

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--api-key TEXT` | *(auto)* | Explicit API key for dashboard auth. |
| `--no-auth` | off | Disable authentication (NOT recommended). |
| `--host TEXT` | `127.0.0.1` | Host to bind to. |
| `--port INT` | `8420` | Port to listen on. |
| `--role-dir PATH` | `.` (cwd) | Directory to scan for role YAML files. |
| `--no-browser` | off | Don't open the browser on startup. |

## Key Resolution

The API key is resolved in order:

1. **Explicit flag** — `--api-key <key>`
2. **Environment variable** — `INITRUNNER_DASHBOARD_API_KEY`
3. **Persisted file** — `~/.initrunner/dashboard.key`
4. **Auto-generate** — a new `secrets.token_urlsafe(32)` key is created and
   persisted to the file above

Steps 3 and 4 only apply when binding to localhost. Non-localhost addresses
require an explicit key (step 1 or 2) or `--no-auth`.

## Key Persistence

The auto-generated key is written to `~/.initrunner/dashboard.key` with `0o600`
permissions (owner read-write only). The file is created atomically via
`os.open()` with `O_WRONLY | O_CREAT | O_TRUNC`. Once persisted, the same key
is reused across restarts — no need to update bookmarks or scripts.

## Binding Safety

Binding to a non-localhost address (`--host 0.0.0.0`, a LAN IP, etc.) triggers
additional checks:

- **Without `--api-key` or env var** — the command exits with an error:

  ```
  Error: Binding to non-localhost address (0.0.0.0) requires an explicit API key.
  Use --api-key <key> or set INITRUNNER_DASHBOARD_API_KEY env var.
  To disable auth entirely (NOT recommended): --no-auth
  ```

  Auto-generated keys are not used for non-localhost because the key is printed
  to the console, which may be visible to others on the network.

- **With `--no-auth`** — a warning is printed but the server starts:

  ```
  WARNING: Running without authentication on a non-localhost address (0.0.0.0).
  The dashboard will be accessible to anyone who can reach this address.
  Agents can execute arbitrary prompts.
  ```

Localhost is defined as `127.0.0.1`, `localhost`, or `::1`.

## How Authentication Works

All HTTP requests to `/api/*` paths (except `/api/health`) pass through an auth
middleware. The middleware extracts the token from one of two sources:

1. **`Authorization: Bearer <token>`** header (preferred)
2. **`?api_key=<token>`** query parameter (fallback)

The token is compared against the configured key using
`hmac.compare_digest()` (constant-time, timing-safe). On failure the middleware
returns **HTTP 401** with `{"detail": "Unauthorized"}`.

The `/api/health` endpoint is always exempt — load balancers and monitoring can
reach it without credentials.

## WebSocket Authentication

HTTP middleware does not intercept WebSocket upgrade requests. Instead, the
chat (`/api/chat/{role_id}`) and daemon (`/api/daemon/{role_id}`) WebSocket
handlers call `verify_websocket_auth()` before accepting the connection.

Token extraction order:

1. `?api_key=<token>` query parameter
2. `Authorization: Bearer <token>` header

On failure the connection is closed with code **1008** (Policy Violation)
without being accepted first.

Pass the token as a query parameter when connecting:

```
ws://127.0.0.1:8420/api/chat/{role_id}?api_key=<token>
```

## Frontend Token Flow

The Next.js frontend manages the token via an app-wide `AuthProvider` gate:

1. **Auth gate** — `AuthProvider` (`components/auth-provider.tsx`) wraps the
   entire app in `layout.tsx`. It renders one of three phases: `loading` (initial
   probe), `login` (full-screen login form), or `ready` (children rendered).
2. **Bootstrap** — on mount the provider checks for a token in this order:
   URL `?api_key=` parameter (highest priority), then `sessionStorage`, then
   probes `/api/roles` to detect whether authentication is required at all.
3. **Login form** — if auth is required and no valid key is present, a
   full-screen login form is rendered. There is no `window.prompt()` fallback.
4. **Store & strip** — a valid key is saved to `sessionStorage` under the key
   `initrunner_api_key`. The `?api_key=` parameter is removed from the URL bar
   via `window.history.replaceState()` to prevent leaking in screenshots or
   browser history.
5. **Attach** — every HTTP request includes `Authorization: Bearer <token>`.
   WebSocket and SSE URLs append `?api_key=<token>`.
6. **401 handling** — `fetchJson()` dispatches a custom
   `window.dispatchEvent(new Event("auth:unauthorized"))` event. `AuthProvider`
   listens for this event and calls `logout()`, which clears `sessionStorage`
   and transitions back to the login form.

The `useAuth()` hook exposes `{ token, login, logout }` for components that need
direct access to auth state.

The token lives in `sessionStorage`, so it survives page reloads but is cleared
when the tab is closed.

## CORS

The dashboard restricts CORS to localhost origins:

```
http://localhost:8420
http://127.0.0.1:8420
http://localhost:3000      # frontend development mode (npm run dev)
http://127.0.0.1:3000     # frontend development mode (npm run dev)
```

Allowed headers: `Authorization`, `Content-Type`, `X-Requested-With`. All HTTP
methods are permitted. The port 3000 origins exist for frontend development mode
— when running the Next.js dev server separately via `cd dashboard && npm run
dev`. In normal usage the bundled frontend is served on port 8420 alongside the
API, so no cross-origin requests occur.

## Rate Limiting

A token-bucket rate limiter protects all `/api/*` paths (except `/api/health`):

| Parameter | Value |
|-----------|-------|
| Sustained rate | 120 requests per minute (2/sec) |
| Burst capacity | 20 requests |
| Exceeded response | HTTP 429 `{"detail": "Too many requests"}` |

The limiter is global (not per-user) and in-memory (single-node only). It uses
`time.monotonic()` and is thread-safe.

## Body Size Limits

POST, PUT, and PATCH requests are limited to **2 MB** (`2 * 1024 * 1024`
bytes). The `Content-Length` header is checked before reading the body. Requests
that exceed the limit receive **HTTP 413** with
`{"detail": "Request body too large"}`. The `/api/health` endpoint is exempt.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `INITRUNNER_DASHBOARD_API_KEY` | API key for dashboard auth. Takes precedence over the persisted key file but not the `--api-key` flag. |

## Examples

### Default (localhost, auto-key)

```bash
initrunner ui
# Key auto-generated, browser opens with token in URL
```

### Explicit key

```bash
initrunner ui --api-key my-secret-key
```

### curl with auth

```bash
curl http://127.0.0.1:8420/api/roles \
  -H "Authorization: Bearer my-secret-key"

# Or via query parameter:
curl "http://127.0.0.1:8420/api/roles?api_key=my-secret-key"
```

### Non-localhost binding

```bash
# Requires explicit key
initrunner ui --host 0.0.0.0 --api-key my-secret-key

# Or via env var
export INITRUNNER_DASHBOARD_API_KEY=my-secret-key
initrunner ui --host 0.0.0.0
```

### Disabling auth

```bash
# Localhost only — safe for local dev
initrunner ui --no-auth

# Non-localhost — prints warning
initrunner ui --host 0.0.0.0 --no-auth
```

### Health check (no auth needed)

```bash
curl http://127.0.0.1:8420/api/health
# {"status":"ok"}
```

## See Also

- [Web Dashboard](../interfaces/dashboard.md) — API reference, frontend pages, architecture
- [Security Hardening](security.md) — role-level `SecurityPolicy` (content
  filtering, rate limiting, tool sandboxing)
