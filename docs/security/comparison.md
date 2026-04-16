# Security Layer Reference

One-page scan of every security primitive InitRunner ships. Each row names the layer, its default state, what it does, the config key that turns it on, and the file it lives in.

For conceptual walkthroughs see [Security Hardening Guide](security.md), [Agent Policy](agent-policy.md), [Docker Sandbox](docker-sandbox.md), and [Guardrails](../configuration/guardrails.md).

## Sandbox

| Layer | Default | What it does | Enable via | Implemented in |
|---|---|---|---|---|
| PEP 578 audit hook | off | Blocks filesystem writes, subprocess spawn, private-IP network, dangerous imports, and eval/exec from inside custom Python tools. | `security.tools.audit_hooks_enabled: true` | `initrunner/agent/sandbox.py` |
| Docker sandbox | off | Runs shell, Python, and script tools inside Docker with read-only rootfs, memory and CPU caps, and network isolation. | `security.docker.enabled: true` or `security.preset: sandbox` | `initrunner/agent/docker_sandbox.py` |
| Per-tool allow/deny globs | no policy = allow | fnmatch patterns on tool arguments enforce per-call permissions. Deny rules evaluate first. | `spec.tools[].permissions.allow` / `.deny` | `initrunner/agent/permissions.py`, `initrunner/agent/schema/tools/_base.py` |

## Policy and content

| Layer | Default | What it does | Enable via | Implemented in |
|---|---|---|---|---|
| InitGuard (CEL authorization) | off | ABAC policy engine checks every tool call and every agent-to-agent delegation against CEL policies. Identity is derived from role metadata. | `INITRUNNER_POLICY_DIR` env var | `initrunner/authz.py` |
| Content input + output policy | off | Validates prompts against a regex blocklist and a length cap before the agent runs; optionally strips or blocks agent output that matches the output blocklist. Optional LLM topic classifier. | `security.content.*` (see [security.md](security.md#content-policy)) | `initrunner/agent/policies.py` |
| Input guard capability | auto-on when content policy is set | PydanticAI `before_run` hook that aborts the run if input validation fails. | auto-registered | `initrunner/agent/capabilities/input_guard.py` |

## Audit and redaction

| Layer | Default | What it does | Enable via | Implemented in |
|---|---|---|---|---|
| SQLite audit trail | on | Append-only log of every run, tool call, trigger event, and outcome. A separate `security_events` table records blocks, rate-limit hits, and sandbox violations. | `security.audit.max_records`, `security.audit.retention_days` | `initrunner/audit/logger.py` |
| Secret scrubbing | off | Regex redaction of GitHub, AWS, OpenAI, Anthropic, Slack, Stripe, SendGrid, Twilio, Discord, and bearer tokens inside logged prompts and outputs. | `security.content.pii_redaction: true`, plus `security.content.redact_patterns` for custom regexes | `initrunner/audit/_redact.py` |

## Network and I/O

| Layer | Default | What it does | Enable via | Implemented in |
|---|---|---|---|---|
| SSRF protection | on (hardcoded) | `http` and `web_reader` tools block RFC 1918, loopback, and link-local addresses at IP level. Per-tool domain allowlists and blocklists layer on top. | `spec.tools[].allowed_domains` / `.blocked_domains` | `initrunner/agent/_urls.py` |
| Subprocess env scrubbing | on | Strips API keys and other sensitive prefixes (OPENAI_API_KEY, ANTHROPIC_API_KEY, AWS_SECRET, DATABASE_URL, plus user additions) from environment passed to MCP, git, and Python-tool subprocesses. | `security.tools.sensitive_env_prefixes`, `security.tools.sensitive_env_suffixes` | `initrunner/agent/_subprocess.py` |
| Rate limiting (`--serve`) | 60 rpm, burst 10 | Token-bucket limiter on API endpoints. Returns HTTP 429 when exhausted. In-memory, single-node. | `security.rate_limit.requests_per_minute`, `security.rate_limit.burst_size` | `initrunner/agent/schema/security.py` and API server |
| CORS and HTTPS enforcement (`--serve`) | off | Rejects cross-origin requests unless whitelisted; rejects non-TLS requests when `require_https` is on. Also caps request body size. | `security.server.cors_origins`, `security.server.require_https`, `security.server.max_request_body_bytes` | `initrunner/agent/schema/security.py` and API server |

## Budgets

| Layer | Default | What it does | Enable via | Implemented in |
|---|---|---|---|---|
| Per-run limits | 50k tokens, 20 tool calls, 300s | Hard caps on tokens, tool invocations, and wall-clock time for a single run. | `spec.guardrails.max_tokens_per_run`, `.max_tool_calls`, `.timeout_seconds` | `initrunner/agent/schema/guardrails.py` |
| Autonomous iteration cap | 10 iterations | Hard cap on the autonomous loop; prevents runaway plan-execute-reflect cycles. | `spec.guardrails.max_iterations`, `.autonomous_timeout_seconds`, `.autonomous_token_budget` | `initrunner/agent/schema/guardrails.py`, `initrunner/runner/autonomous.py` |
| Cumulative token budgets | off | Per-session (REPL), per-daemon lifetime, and per-daemon-day token caps. | `spec.guardrails.session_token_budget`, `.daemon_token_budget`, `.daemon_daily_token_budget` | `initrunner/agent/schema/guardrails.py` |
| USD cost budgets | off | Daily and weekly USD caps on daemon spend, measured via `genai-prices`. Daemon stops firing triggers when the cap is hit. | `spec.guardrails.daemon_daily_cost_budget`, `.daemon_weekly_cost_budget` | `initrunner/agent/schema/guardrails.py` |

## Presets

The `security.preset` field applies a preconfigured bundle of the above layers. See [security.md](security.md#security-presets) for the full preset table.

| Preset | Who it's for |
|---|---|
| `public` | Agents exposed to untrusted input (webhooks, bots, public APIs). PII redaction, injection-pattern blocklist, HTTPS required, 30 rpm rate limit, 10k prompt cap. |
| `internal` | Authenticated internal tools. 120 rpm rate limit, otherwise defaults. |
| `sandbox` | Public agents that run untrusted code. Inherits `public` plus Docker sandbox with `network: none`, read-only rootfs, 256m memory, 1 CPU. |
| `development` | Local development. Filtering disabled, 9999 rpm, 500k prompt cap. |
