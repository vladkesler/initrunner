# Known Gaps

Deferred work with enough context to pick up cold. Each entry says what is
wrong, how to reproduce it, and what has already been ruled out. Delete an
entry when it ships.

## Provider SDKs are split across httpx and httpx2

**Added:** 2026.8.9.

`build_retrying_async_client()` in `initrunner/agent/executor_retry.py` picks
the HTTP library per provider, because the SDKs disagree about which one they
accept:

| Provider SDK | legacy `httpx` | `httpx2` |
|---|---|---|
| openai, google, mistral, cohere | accepted | accepted |
| anthropic (>=1.0.0) | **TypeError** | accepted |
| groq | accepted | **TypeError** |

So `_LEGACY_HTTPX_PROVIDERS = frozenset({"groq"})` selects `AsyncTenacityTransport`
plus `httpx.AsyncClient` for groq, and `AsyncHTTPX2TenacityTransport` plus
`httpx2.AsyncClient` for everyone else. Passing the wrong one is a `TypeError`
raised from inside the SDK constructor, not a degraded mode, which is why the
choice cannot be left to the caller.

Two separate things have to happen before this goes away.

**1. groq migrates to httpx2.** Then `_LEGACY_HTTPX_PROVIDERS` empties, and the
whole `legacy` branch, the `import httpx` in that module, and the
`AsyncTenacityTransport` import go with it. To check:

```python
from pydantic_ai.providers.groq import GroqProvider
import httpx2
GroqProvider(api_key="k", http_client=httpx2.AsyncClient())  # TypeError today
```

**2. pydantic-ai fixes `AnthropicProvider`.** As of pydantic-ai 2.32.1 it builds
a legacy `httpx` client internally, which anthropic 1.0.0 rejects, so
`AnthropicProvider(api_key="k")` raises `TypeError` with no client passed at all.
Anthropic 1.0.0 shipped 2026-08-20 19:58 UTC and pydantic-ai 2.32.1 shipped the
same day at 02:26 UTC, seventeen hours earlier, so upstream had not seen it yet.
Our explicit httpx2 client is what makes Anthropic work at all right now. That
stays correct after they fix it (it is what their own deprecation warning asks
for), but the reason for it changes, so re-read this entry then rather than
assuming it is still load-bearing.

Also revisit the floors in `pyproject.toml` (`pydantic-ai-slim>=2.32.1`, the
explicit `httpx2>=2.12.0` core dependency) once pydantic-ai v3 lands, since v3
removes the deprecated `httpx` transports entirely.

## The site docs have no schema guard

`tests/test_docs_yaml.py` validates every fenced YAML block in `README*.md` and
`docs/**/*.md` against the real schema, which is what caught the 2026.8.4
drift. The docs site (`initrunner-dashboard`, `frontend/content/docs/*.mdx`)
has no equivalent, so it can drift again silently and nothing will fail.

The blocker is that the check needs the `initrunner` package installed to
import the schema, and the site repo is a pnpm project with no Python
toolchain. Options, roughly in order of how much work they are:

1. Run the check from this repo in CI against a checked-out sibling site repo.
2. Add a small Python dev dependency group to the site repo just for this.
3. Have the existing docs-sync workflow validate as part of the sync.

A working implementation is not in the repo; it was written as a throwaway
during the 2026.8.5 sweep. It is about 60 lines: extract fenced blocks, skip an
allowlist of four non-agent examples, call `classify_mapping` then
`normalize_mapping`. Reuse the logic in `tests/test_docs_yaml.py`.
