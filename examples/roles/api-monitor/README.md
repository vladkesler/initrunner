# API Monitor

Pings your API endpoints every five minutes, remembers response times across days, and alerts Slack when latency is trending up -- not just when things are already on fire. Sends recovery notices when endpoints come back.

## Quick start

```bash
# Install
initrunner install vladkesler/api-monitor

# Edit endpoints.md with your URLs (see Customization below)

# Set your credentials
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
export OPENAI_API_KEY="your-api-key"

# Start monitoring
initrunner daemon role.yaml
```

The agent checks your endpoints every 5 minutes during active hours (6:00-22:00 UTC by default).

## Prerequisites

1. **Slack incoming webhook** -- Create one at [Slack API > Incoming Webhooks](https://api.slack.com/messaging/webhooks). Point it at the channel where you want alerts posted.
2. **curl** -- Pre-installed on most systems. Used for endpoint health checks.
3. **openssl** (optional) -- For SSL certificate expiry checks. The agent skips SSL checks if openssl is not available.

## How it works

1. The heartbeat trigger reads `endpoints.md` on a 5-minute interval
2. For each endpoint, curl checks HTTP status and response time in one call
3. The agent recalls previous check results from episodic memory
4. Current latency is compared against the historical baseline (median of last 10 checks)
5. If an endpoint is down, degraded, or recovered, Slack gets an alert
6. Healthy endpoints are recorded silently -- no Slack noise

## Example session

```
[heartbeat] Reading endpoints.md

> shell: curl -s -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 https://api.example.com/health
200 0.142

> shell: curl -s -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 https://api.example.com/api/v1/status
200 0.891

> recall("api.example.com/api/v1/status check")
Last 5 checks: 210ms, 245ms, 380ms, 520ms, 891ms

> think: /api/v1/status baseline is ~230ms. Current 891ms is 3.9x baseline.
> This is the 4th consecutive elevated reading. Trend: degrading.

> send_slack_message:
:warning: *DEGRADED* api.example.com/api/v1/status
Latency 891ms (baseline ~230ms, 3.9x elevated)
Trending up over last 4 checks: 245ms -> 380ms -> 520ms -> 891ms
_2026-03-19 14:05 UTC_

> record_episode: /api/v1/status 200 891ms degraded (4th consecutive)

{
  "checks": [
    {
      "endpoint": "https://api.example.com/health",
      "status_code": 200,
      "latency_ms": 142,
      "healthy": true,
      "error": ""
    },
    {
      "endpoint": "https://api.example.com/api/v1/status",
      "status_code": 200,
      "latency_ms": 891,
      "healthy": false,
      "error": "latency 3.9x above baseline"
    }
  ],
  "summary": { "total": 4, "healthy": 3, "degraded": 1, "down": 0 },
  "alerts": [
    {
      "endpoint": "https://api.example.com/api/v1/status",
      "type": "degraded",
      "message": "Latency 891ms, 3.9x baseline, 4th consecutive elevated reading",
      "severity": "warning"
    }
  ],
  "timestamp": "2026-03-19T14:05:00Z"
}
```

## Example prompts (manual mode)

```
Check all endpoints now
How is api.example.com/health performing this week?
Check the SSL certificate for api.example.com
Run a deep check on all endpoints including response validation
What's the latency trend for the /api/v1/status endpoint?
```

## What's inside

- **Heartbeat trigger** -- Reads endpoints.md every 5 minutes during active hours (6:00-22:00 UTC). Edit `active_hours` to match your business hours.
- **Memory-powered trend detection** -- Every check result is stored as an episodic memory. The agent compares current latency against a rolling baseline of recent checks.
- **Recovery alerts** -- When an endpoint that was down comes back up, the agent sends a recovery notice to Slack so your team knows the incident is over.
- **Auto-discovered skills** -- Latency analysis, SSL certificate checking, and response validation. Activated on demand when deeper investigation is needed.
- **Structured JSON output** -- Every heartbeat produces a typed report with check results, summary counts, and alert details.
- **Slack alerts** -- Posts only when something changes (down, degraded, recovered). Healthy checks are silent.

## Customization

### Endpoints

Edit `endpoints.md` to add your URLs:

```markdown
# API Health Checks

- [ ] GET https://api.yourcompany.com/health
- [ ] GET https://api.yourcompany.com/api/v1/status
- [ ] GET https://internal.yourcompany.com/readiness
```

### Check interval

```yaml
triggers:
  - type: heartbeat
    interval_seconds: 300   # every 5 minutes (default)
    active_hours: [6, 22]   # check only during these hours (UTC)
    timezone: UTC            # change to your timezone
```

### Slack configuration

```yaml
tools:
  - type: slack
    webhook_url: "${SLACK_WEBHOOK_URL}"
    default_channel: "#ops-alerts"
    username: API Monitor
    icon_emoji: ":satellite:"
```

### Memory sizing

```yaml
memory:
  episodic:
    max_episodes: 2000    # check results for trend detection
  semantic:
    max_memories: 500     # endpoint baselines, known issues
  procedural:
    max_procedures: 50    # learned patterns
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
