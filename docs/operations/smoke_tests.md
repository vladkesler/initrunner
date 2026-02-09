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
initrunner init --template rag
initrunner validate role.yaml

initrunner init --template memory
initrunner validate role.yaml
```

Both templates should scaffold a valid role that passes validation.

## Compose

### Validate compose definitions

```bash
initrunner compose validate examples/compose/email-pipeline/compose.yaml
initrunner compose validate examples/compose/content-pipeline/compose.yaml
```

Both should exit 0 and print a service summary table.

### Live compose smoke test

Running `compose up` requires API keys and is not suitable for automated smoke testing. To verify end-to-end manually:

```bash
# Create a drafts directory with a test file
mkdir -p examples/compose/content-pipeline/drafts
echo "# Test Draft\n\nA short article about testing." > examples/compose/content-pipeline/drafts/test.md

# Start the pipeline (requires OPENAI_API_KEY)
initrunner compose up examples/compose/content-pipeline/compose.yaml
```

The content-watcher service should detect `test.md` via its `process_existing: true` trigger and delegate a research brief to the researcher.

### Systemd command help

Verify the systemd lifecycle commands are wired correctly. These only check CLI plumbing and do not require systemd to be running.

```bash
initrunner compose install --help
initrunner compose uninstall --help
initrunner compose start --help
initrunner compose stop --help
initrunner compose restart --help
initrunner compose status --help
initrunner compose logs --help
```

All commands should exit 0 and print usage information.
