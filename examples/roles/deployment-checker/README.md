# Deployment Checker

Autonomous deployment verification agent. Given URLs to check, it creates a structured checklist, verifies each endpoint, investigates failures, and sends a Slack summary.

## Quick start

```bash
# Install
initrunner install vladkesler/deployment-checker

# Verify endpoints
initrunner run deployment-checker -a -p "Check https://api.example.com/health and https://api.example.com/ready"

# Post-deploy verification
initrunner run deployment-checker -a -p "Verify staging deployment: https://staging.example.com/api/v1/status"
```

Requires `SLACK_WEBHOOK_URL` environment variable for Slack notifications.

## How it works

1. Creates a todo list with one item per URL (uses `batch_add_todos`)
2. Runs `curl` against each URL, recording response codes and timing
3. Marks each item completed (2xx) or failed (non-2xx)
4. On failure, adds a high-priority retry or investigation item
5. Sends a pass/fail summary to Slack
6. Calls `finish_task` with the overall status

## Example prompts

```
Check https://api.example.com/health and https://api.example.com/ready
Verify staging deployment: https://staging.example.com/api/v1/status https://staging.example.com/api/v1/docs
Run health checks on all three environments: https://dev.example.com/health https://staging.example.com/health https://prod.example.com/health
```

## Configuration

The shell tool is restricted to `curl` only. Adjust the Slack webhook in `role.yaml`:

```yaml
tools:
  - type: slack
    webhook_url: "${SLACK_WEBHOOK_URL}"
    default_channel: "#deployments"
```

## Changing the model

Edit `spec.model` in `role.yaml`:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
```
