# Smoke Tests

Manual smoke tests for verifying example roles load and validate correctly. Run these after changes to schema loading, tool wiring, or MCP transport.

## Validate all example roles

```bash
initrunner validate examples/roles/hello-world.yaml
initrunner validate examples/roles/code-reviewer.yaml
initrunner validate examples/roles/memory-assistant.yaml
initrunner validate examples/roles/support-agent/support-agent.yaml
initrunner validate examples/roles/rag-agent/rag-agent.yaml
initrunner validate examples/roles/multi-agent/coordinator.yaml
```

All commands should exit 0 and print `Valid`.

## Dry-run execution

Verify the full pipeline (load, build agent, execute) works without API keys:

```bash
initrunner run examples/roles/hello-world.yaml -p "Hi" --dry-run
initrunner run examples/roles/code-reviewer.yaml -p "Review recent changes" --dry-run
initrunner run examples/roles/memory-assistant.yaml -p "Remember that I like coffee" --dry-run
```

Each should print `[dry-run] Simulated response.` and exit 0.

## MCP transport construction

The `support-agent/support-agent.yaml` role uses an MCP stdio tool. Validate it loads without a transport error:

```bash
initrunner validate examples/roles/support-agent/support-agent.yaml
```

This exercises the `MCPServerStdio` path in `initrunner/mcp/server.py`. Previously this crashed with:

```
ValueError: Could not infer a valid transport from: MCPServerStdio(...)
```

## Scaffolding templates

```bash
cd $(mktemp -d)
initrunner new --template rag
initrunner validate role.yaml

initrunner new --template memory
initrunner validate role.yaml
```

Both templates should scaffold a valid role that passes validation.

## Flow

### Validate flow definitions

```bash
initrunner flow validate examples/flows/email-pipeline/flow.yaml
initrunner flow validate examples/flows/content-pipeline/flow.yaml
```

Both should exit 0 and print an agent summary table.

### Live flow smoke test

Running `flow up` requires API keys and is not suitable for automated smoke testing. To verify end-to-end manually:

```bash
# Create a drafts directory with a test file
mkdir -p examples/flows/content-pipeline/drafts
echo "# Test Draft\n\nA short article about testing." > examples/flows/content-pipeline/drafts/test.md

# Start the pipeline (requires OPENAI_API_KEY)
initrunner flow up examples/flows/content-pipeline/flow.yaml
```

The content-watcher agent should detect `test.md` via its `process_existing: true` trigger and delegate a research brief to the researcher.

### Systemd command help

Verify the systemd lifecycle commands are wired correctly. These only check CLI plumbing and do not require systemd to be running.

```bash
initrunner flow install --help
initrunner flow uninstall --help
initrunner flow start --help
initrunner flow stop --help
initrunner flow restart --help
initrunner flow status --help
initrunner flow logs --help
```

All commands should exit 0 and print usage information.
