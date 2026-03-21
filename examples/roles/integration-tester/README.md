# Integration Tester

Runs your integration tests, diagnoses failures by checking service health, database connectivity, and environment configuration, and classifies each failure so your team knows what to fix first. Learns flaky patterns across runs.

## Quick start

```bash
# Install
initrunner install vladkesler/integration-tester

# Set your credentials
export OPENAI_API_KEY="your-api-key"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."

# Run once
initrunner run role.yaml -p "Run integration tests"

# Start as daemon (daily 6am UTC + webhook trigger)
initrunner run role.yaml --daemon
```

## Prerequisites

1. **Test framework** -- pytest, jest, or equivalent with integration test markers/directories.
2. **curl** -- For API endpoint health probing. Pre-installed on most systems.
3. **Database CLI tools** (optional) -- pg_isready, redis-cli, sqlite3, mysql as needed for database connectivity checks.
4. **docker/docker-compose** (optional) -- For containerized service health checks.
5. **Slack webhook** -- For failure and recovery alerts. Create one at [Slack API > Incoming Webhooks](https://api.slack.com/messaging/webhooks).

## How it works

1. Checks environment variables and configuration
2. Verifies all dependent services are healthy before running tests
3. Runs the integration test suite
4. For each failure, diagnoses the root cause and classifies it (bug, flaky, environment, dependency, configuration)
5. Checks memory for known flaky tests and previous failure patterns
6. Alerts Slack on failures (with classification) or recovery
7. Records results for trend detection across runs

## Example session

```
> initrunner run role.yaml -p "Run integration tests"

[checking environment] Found pytest, docker-compose, .env

> shell: curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health
200

> shell: pg_isready -h localhost -p 5432
localhost:5432 - accepting connections

> shell: pytest tests/integration/ -v --tb=short
========================= test session starts =========================
tests/integration/test_user_api.py::test_create_user PASSED
tests/integration/test_user_api.py::test_list_users PASSED
tests/integration/test_payment_flow.py::test_checkout FAILED
tests/integration/test_payment_flow.py::test_refund PASSED
tests/integration/test_notifications.py::test_send_email PASSED
tests/integration/test_notifications.py::test_webhook_delivery FAILED
tests/integration/test_search.py::test_full_text PASSED
tests/integration/test_search.py::test_filters PASSED
tests/integration/test_auth.py::test_login PASSED
tests/integration/test_auth.py::test_token_refresh PASSED
tests/integration/test_reports.py::test_generate_pdf PASSED
tests/integration/test_reports.py::test_export_csv PASSED
=================== 2 failed, 10 passed in 34.2s =====================

> read_file("tests/integration/test_payment_flow.py", lines="45-70")
[ConnectionError: HTTPSConnectionPool -- Stripe API returned 503]

> activate_skill("service-health-check")

> shell: curl -s -o /dev/null -w '%{http_code}' https://api.stripe.com/v1/charges
503

> recall("test_webhook_delivery flaky")
Found: test_webhook_delivery failed 3 of last 10 runs, passed on retry each time

> think: test_checkout failure is a dependency issue -- Stripe API is returning
> 503. test_webhook_delivery is a known flaky test from memory -- it has failed
> intermittently in 3 of the last 10 runs.

> send_slack_message:
:rotating_light: *Integration Test Failures* (2/12 failed)

*test_checkout* -- dependency
Stripe API returning 503. External service outage.

*test_webhook_delivery* -- flaky
Known flaky test (3 of last 10 runs). Passes on retry.

_2026-03-19 06:00 UTC | 10 passed, 2 failed, 0 skipped_

> record_episode: 12 tests, 10 passed, 2 failed, 34.2s, dependency:1 flaky:1

{
  "suite_results": {
    "passed": 10,
    "failed": 2,
    "skipped": 0,
    "errors": 0,
    "duration_seconds": 34.2
  },
  "failures": [
    {
      "test_name": "test_payment_flow.py::test_checkout",
      "error_message": "ConnectionError: Stripe API returned 503",
      "classification": "dependency",
      "diagnosis": "Stripe API is returning 503 Service Unavailable. This is an external service outage, not a code issue.",
      "suggested_fix": "Wait for Stripe to recover. Check https://status.stripe.com for incident updates."
    },
    {
      "test_name": "test_notifications.py::test_webhook_delivery",
      "error_message": "AssertionError: expected webhook callback within 5s",
      "classification": "flaky",
      "diagnosis": "Known flaky test -- failed 3 of last 10 runs. Timing-dependent webhook callback with a tight 5s timeout.",
      "suggested_fix": "Increase webhook callback timeout to 15s or add retry logic in the test."
    }
  ],
  "service_health": [
    {
      "service": "app (localhost:8080)",
      "status": "healthy",
      "details": "HTTP 200"
    },
    {
      "service": "postgres (localhost:5432)",
      "status": "healthy",
      "details": "accepting connections"
    },
    {
      "service": "Stripe API",
      "status": "down",
      "details": "HTTP 503 Service Unavailable"
    }
  ],
  "summary": "2 of 12 integration tests failed. 1 dependency failure (Stripe API outage), 1 known flaky test. No code bugs detected. All local services healthy."
}
```

## Example prompts

```
Run integration tests
Run only the API integration tests
Diagnose why test_payment_flow keeps failing
Check if all services are healthy before testing
What tests have been flaky this week?
```

## What's inside

- **Failure classification** -- Each failure is categorized as bug, flaky, environment, dependency, or configuration so your team knows what to fix.
- **Service health pre-check** -- Verifies databases, APIs, and dependent services are up before running tests.
- **Flaky test detection** -- Memory tracks test results across runs. Tests that fail intermittently are flagged as flaky.
- **Auto-discovered skills** -- API contract testing, database verification, service health checks, and environment diagnostics. Activated on demand during failure diagnosis.
- **Slack alerts** -- Posts on failures and recovery. Silent when all tests pass and were passing before.

## Customization

### Triggers

```yaml
triggers:
  - type: webhook
    path: /test-trigger
    port: 9091
    method: POST
    secret: "${WEBHOOK_SECRET}"
  - type: cron
    schedule: "0 6 * * *"
    timezone: UTC
```

### Slack configuration

```yaml
tools:
  - type: slack
    webhook_url: "${SLACK_WEBHOOK_URL}"
    default_channel: "#test-alerts"
    username: Integration Tester
    icon_emoji: ":test_tube:"
```

### Shell commands

```yaml
tools:
  - type: shell
    allowed_commands: [pytest, python, uv, npm, npx, docker, docker-compose, curl, pg_isready, redis-cli, sqlite3, mysql, make]
```

### Memory limits

```yaml
memory:
  semantic:
    max_memories: 500
  episodic:
    max_episodes: 500    # test run history for flaky detection
  procedural:
    max_procedures: 100  # diagnosis patterns
```

## Changing the model

Edit `spec.model` in `role.yaml`. Memory uses embeddings that inherit from the model provider -- Anthropic falls back to OpenAI embeddings (`OPENAI_API_KEY` needed).

```yaml
spec:
  model:
    provider: anthropic
    name: claude-sonnet-4-5-20250929
  memory:
    embeddings:
      provider: google
      model: text-embedding-004
```
