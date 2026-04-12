# A2A Demo -- Agent-to-Agent Delegation

This example shows two agents communicating via the A2A protocol:

- **researcher.yaml** -- a research agent exposed as an A2A server
- **coordinator.yaml** -- a coordinator that delegates to the researcher over A2A

## Usage

Start the research agent as an A2A server:

```bash
initrunner a2a serve researcher.yaml --port 8000
```

In a second terminal, run the coordinator:

```bash
initrunner run coordinator.yaml -p "What are the latest developments in quantum computing?"
```

The coordinator will call `delegate_to_a2a_researcher(...)` which sends a JSON-RPC `message/send` request to the A2A server, polls for completion, and returns the result.

## With Authentication

```bash
# Server
export A2A_KEY="my-secret-key"
initrunner a2a serve researcher.yaml --api-key "$A2A_KEY"

# Coordinator -- set the header env var
export RESEARCH_API_KEY="Bearer my-secret-key"
```

Then update coordinator.yaml to include `headers_env`:

```yaml
agents:
  - name: a2a-researcher
    url: http://localhost:8000
    description: Research agent
    headers_env:
      Authorization: RESEARCH_API_KEY
```
