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
choice cannot be left to the caller. pydantic-ai 2.56 deprecates
`AsyncTenacityTransport` (removed in v3). `_legacy_transport()` ignores that
one warning. Do not delete the ignore until groq accepts httpx2 and the
transport goes away.

Two separate things have to happen before this goes away.

**1. groq migrates to httpx2.** Then `_LEGACY_HTTPX_PROVIDERS` empties, and the
whole `legacy` branch, the `import httpx` in that module, and the
`AsyncTenacityTransport` import go with it. To check:

```python
from pydantic_ai.providers.groq import GroqProvider
import httpx2
GroqProvider(api_key="k", http_client=httpx2.AsyncClient())  # TypeError today
```

**2. pydantic-ai fixes `AnthropicProvider`.** Done in 2.33.0. Checked on 2.56.0:
`AnthropicProvider(api_key="k")` constructs with no client, and it builds an
httpx2 client internally. InitRunner still passes its own httpx2 client,
because that client is the retry transport (`AsyncHTTPX2TenacityTransport`),
not because Anthropic would otherwise fail.

The split stays until groq accepts httpx2. Revisit the `httpx2>=2.12.0` core
dependency once pydantic-ai v3 removes the deprecated `httpx` transports.

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
