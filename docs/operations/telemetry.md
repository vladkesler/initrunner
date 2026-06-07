# Usage Telemetry

InitRunner collects anonymous usage telemetry so the maintainers can see whether
it is being used and which parts are used, and decide what to work on next. It is
**opt-out**: it runs by default, sends only an allowlist of non-identifying
values, and can be turned off with one command or an environment variable.

This is separate from two things it is often confused with:

- **Agent observability** (`initrunner[observability]`, OpenTelemetry) traces
  *your* agent runs to *your* backend. InitRunner never receives that data.
- **The audit trail** (`~/.initrunner/audit.db`) is a local, HMAC-signed log of
  agent actions. It is never transmitted.

## What is collected

Telemetry is built from a fixed allowlist in
[`initrunner/telemetry/_events.py`](../../initrunner/telemetry/_events.py),
which is the source of truth. Two events are sent:

### `cli_command` (once per command)

| Property | Example | Notes |
|---|---|---|
| `command` | `run`, `new`, `doctor` | Command name only, from a known list; anything else becomes `other`. Never arguments. |
| `status` | `ok`, `error` | Outcome. |
| `exit_code` | `0`, `1` | Process exit code. |
| `error_kind` | `FileNotFoundError` | Exception class name only, from a known list, else `OtherError`. Never the message or traceback. |
| `duration_bucket` | `<1s`, `1-5s`, `5-30s`, `30s+` | Coarse bucket, never the raw time. |
| `is_tty` | `true` | Whether stdin is a terminal. |
| `is_ci` | `false` | Whether a CI environment was detected. |

### `cli_first_run` (once per install)

| Property | Example | Notes |
|---|---|---|
| `install_method` | `pip`, `pipx`, `uv`, `docker`, `unknown` | Best-effort. |

### On every event

`os` (`Linux` / `Darwin` / `Windows`), `python_version` (major.minor, e.g.
`3.12`), `initrunner_version`, and `$lib` (`initrunner-cli`). Every event is sent
with `$process_person_profile: false` (anonymous, no person profile is created),
`$geoip_disable: true` (no server-side geolocation), and `$ip: 0.0.0.0` (the real
source IP is never stored).

## What is never collected

Prompts, role or skill file contents, file paths, command arguments or flag
values, API keys, model names or aliases, MCP server names or URLs, exception
messages or tracebacks, raw durations, hostnames, and usernames. As a second
layer, every string value passes through the audit secret scrubber before it
leaves the process.

A note on IP addresses: InitRunner never puts an IP, hostname, or username in the
payload. Any HTTPS request still exposes the source IP at the network layer, so
every event overrides it: `$ip` is set to `0.0.0.0` (PostHog stores the sent
value instead of the request IP) and `$geoip_disable: true` skips geolocation.
The real IP is therefore never stored. As a backstop you can also enable
"Discard client IP data" in the PostHog project settings, which strips the IP
server-side for every event.

## The anonymous install id

Telemetry is tied to a random UUID (`install_id`) generated once and stored in
`~/.initrunner/telemetry.json` (mode `0600`). It is not derived from your
username, hostname, or home directory, so it carries no identifying information.
It exists only so distinct installs can be counted. Rotate it any time with
`initrunner telemetry reset`.

## Turning it off

Any one of these disables the CLI telemetry. They are checked before anything is
sent, and a disabled run does no network work.

```bash
initrunner telemetry disable     # persistent opt-out
export DO_NOT_TRACK=1             # the cross-tool standard
export INITRUNNER_TELEMETRY=off   # project-specific switch
```

Telemetry is also off by default in CI (when a `CI` environment variable is set).
Re-enable with `initrunner telemetry enable`. Check the current state, the reason
it is off, your install id, and the config path with:

```bash
initrunner telemetry status
initrunner doctor                # also shows a telemetry status line
```

On the first run where telemetry is active, a one-time notice is printed to
stderr before anything is sent, so disclosure always precedes collection (this
holds for non-interactive and daemon runs too).

## Where the data goes

Events go to PostHog US Cloud (`https://us.i.posthog.com`, project 458252).
PostHog is the data processor. The shipped project key is a public, write-only
ingestion key; it grants capture-only access. To request deletion, run
`initrunner telemetry status` to find your `install_id` and email
`contact@initrunner.ai` with it.

## The dashboard

The web dashboard uses `posthog-js` with the same posture: no autocapture, no
session recording, no heatmaps, no input contents, and anonymous events. It is
disabled when the browser sets Do Not Track, when you choose "Disable" on the
first-run notice (or have previously opted out), or when no key is configured at
build time. The opt-out is stored in the browser's local storage.

## Development and overrides

| Variable | Effect |
|---|---|
| `INITRUNNER_TELEMETRY_DEBUG=1` | Print the event JSON to stderr and send nothing. |
| `INITRUNNER_POSTHOG_KEY` | Override the project key (point a dev build at a test project). |
| `INITRUNNER_POSTHOG_HOST` | Override the host. |
| `VITE_POSTHOG_KEY` / `VITE_POSTHOG_HOST` | Same overrides for the dashboard, at build time. |

To see exactly what an invocation would send without sending it:

```bash
INITRUNNER_TELEMETRY_DEBUG=1 initrunner doctor
```
