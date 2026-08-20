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

## Unknown keys are silently dropped in most config sections

**Status:** partially fixed in 2026.8.5.

Every Pydantic model reachable from `AgentDocument` defaults to
`extra="ignore"`. A typo in a nested section validates clean and the setting
vanishes. `memory: {retenion_days: 30}` is accepted and does nothing.

`AgentDocument` itself is `extra="forbid"`, so top-level typos are caught.
2026.8.5 extended that to the `security` and `observability` trees (12 and 1
models). The remaining leaves are still `extra="ignore"`:

`autonomy.py`, `execution.py`, `guardrails.py`, `ingestion.py`, `memory.py`,
`output.py`, `reasoning.py`, `base.py`, `role.py`, `triggers.py`, `sinks.py`
(about 38 models).

Adding `model_config = ConfigDict(extra="forbid")` across all of them was
tried and reverted. It breaks three tests:

```
tests/test_memory_import_cli.py::TestMemoryImportCli::test_memory_import_invalid_json
tests/test_memory_import_cli.py::TestMemoryImportCli::test_memory_import_non_array_json
tests/test_memory_import_cli.py::TestMemoryImportCli::test_memory_import_file_not_found
```

Diagnose those three first. They are the whole blocker; the rest of the suite
(6641 tests) passed with the change in place. Do it in one pass rather than
per-file, because a half-tightened schema is worse than either end state: it
teaches users that typos are caught when they usually are not.

## Schema errors lost their per-field paths

`initrunner validate` used to report a dotted path per issue. Since the flat
migration, any Pydantic failure on the document collapses into a single issue
whose field is the literal string `document`, with the real path buried in the
message body:

```
[ERROR] document
  1 validation error for AgentDocument
model.provider
  Input should be a valid string [type=string_type, input_value=123, ...]
```

Nested flow issues keep their prefix (`agents.worker.document`), so the file is
still identifiable, just not the field. The docs were rewritten in 2026.8.5 to
describe what actually happens rather than what used to. Restoring per-field
paths means unpacking `ValidationError.errors()` into one `ValidationIssue` per
entry in `services/yaml_validation.py`, which would also bring back the
per-error fix hints that the panel still has code for.

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
