# Email Agent

Monitors your inbox every 5 minutes, triages new messages by priority, alerts Slack when something needs attention, and drafts context-aware replies in interactive mode. Learns your contacts, communication style, and triage preferences over time.

## Quick start

```bash
# Install
initrunner install vladkesler/email-agent

# Set your credentials
export EMAIL_IMAP_HOST="imap.gmail.com"
export EMAIL_SMTP_HOST="smtp.gmail.com"
export EMAIL_USER="you@gmail.com"
export EMAIL_PASS="your-app-password"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
export OPENAI_API_KEY="your-api-key"

# Start monitoring (daemon mode)
initrunner run role.yaml --daemon

# Or use interactively
initrunner run role.yaml -i
```

## Prerequisites

1. **Email account with IMAP/SMTP access** -- Gmail, Outlook, Fastmail, or any provider with IMAP support. You need an app password (not your regular password) for most providers.
2. **Slack incoming webhook** (optional) -- Create one at [Slack API > Incoming Webhooks](https://api.slack.com/messaging/webhooks). Without it, the agent still triages and records in memory but won't send alerts.

## Provider setup

### Gmail

```bash
export EMAIL_IMAP_HOST="imap.gmail.com"
export EMAIL_SMTP_HOST="smtp.gmail.com"
export EMAIL_USER="you@gmail.com"
export EMAIL_PASS="your-16-char-app-password"
```

Generate an app password at [Google Account > Security > App passwords](https://myaccount.google.com/apppasswords). Requires 2FA enabled.

### Outlook / Microsoft 365

```bash
export EMAIL_IMAP_HOST="outlook.office365.com"
export EMAIL_SMTP_HOST="smtp.office365.com"
export EMAIL_USER="you@outlook.com"
export EMAIL_PASS="your-app-password"
```

### Fastmail

```bash
export EMAIL_IMAP_HOST="imap.fastmail.com"
export EMAIL_SMTP_HOST="smtp.fastmail.com"
export EMAIL_USER="you@fastmail.com"
export EMAIL_PASS="your-app-password"
```

### Custom IMAP/SMTP

Edit the tool config in `role.yaml` directly:

```yaml
tools:
  - type: email
    imap_host: "mail.example.com"
    smtp_host: "mail.example.com"
    imap_port: 993       # default
    smtp_port: 587       # default, use 465 for SSL
    username: "${EMAIL_USER}"
    password: "${EMAIL_PASS}"
    use_ssl: true        # default
    read_only: false
```

## How it works

**Daemon mode** -- The cron trigger fires every 5 minutes. Each tick:
1. Searches for UNSEEN messages
2. Reads and triages each new email (URGENT / REPLY_NEEDED / FYI / NEWSLETTER / NOTIFICATION / SPAM)
3. Checks sender profiles in memory for context
4. Alerts Slack for urgent and reply-needed messages
5. Batches low-priority messages into a digest if 3+
6. Records every triage decision in episodic memory

**Interactive mode** -- You chat with the agent to:
- Draft and send replies (always shows draft before sending)
- Search your inbox with natural language
- Browse folders
- Teach the agent your preferences ("emails from billing@ are always urgent")

## Example daemon session

```
[cron] */5 * * * * -- Inbox check

> search_inbox(query="UNSEEN")
3 unread messages found

> read_email(message_id="<abc123@example.com>")
From: Sarah Chen <sarah@bigclient.com>
Subject: URGENT: Production API returning 500s
Date: Wed, 19 Mar 2026 10:32:00 -0400

Our production integration has been failing since 10am...

> think: Known sender (sarah@bigclient.com -- BigClient, VP Engineering).
> Subject contains "URGENT", mentions production failure. Direct request
> with time pressure. Category: URGENT (high confidence).

> recall("sarah@bigclient.com sender_profile")
Sarah Chen, VP Engineering at BigClient. Primary contact for API integration.

> record_episode("sarah@bigclient.com | URGENT: Production API returning 500s | URGENT | 2026-03-19T14:32Z", category="triage")

> send_slack_message:
:rotating_light: *URGENT* from Sarah Chen (BigClient)
_URGENT: Production API returning 500s_
Production integration failing since 10am, requesting immediate investigation.
_2026-03-19 14:32 UTC_

> read_email(message_id="<def456@example.com>")
From: GitHub <notifications@github.com>
Subject: [repo] PR #847 merged

> think: Noreply sender, system notification, automated content.
> Category: NOTIFICATION (high confidence).

> record_episode("notifications@github.com | PR #847 merged | NOTIFICATION | 2026-03-19T14:32Z", category="triage")

> read_email(message_id="<ghi789@example.com>")
From: Tech Weekly <digest@techweekly.io>
Subject: This week in AI: GPT-5 benchmarks

> think: Newsletter sender, contains unsubscribe link, recurring digest.
> Category: NEWSLETTER (high confidence).

> record_episode("digest@techweekly.io | This week in AI | NEWSLETTER | 2026-03-19T14:32Z", category="triage")

Triage complete. 1 urgent alert sent. 2 low-priority messages recorded.
```

## Example interactive session

```
$ initrunner run role.yaml -i

You: Reply to Sarah's urgent email about the 500s

> read_email(message_id="<abc123@example.com>")
> recall("sarah@bigclient.com sender_profile")
> recall("style_rule")

Draft reply to: Sarah Chen <sarah@bigclient.com>
Subject: Re: URGENT: Production API returning 500s
---

Hi Sarah,

Thanks for flagging this. We've identified the issue and the team is on
it now. The root cause appears to be a configuration change that went
out at 9:45am -- we're rolling it back.

I'll send you a status update within the hour. In the meantime, retries
should start succeeding as the rollback propagates.

Best,
Alex

---
Send this reply? (yes / edit / cancel)

You: yes

> send_email(to="sarah@bigclient.com", subject="Re: URGENT: Production API returning 500s", body="...", reply_to="<abc123@example.com>")
Email sent to sarah@bigclient.com

> record_episode("Replied to sarah@bigclient.com re: Production API 500s -- confirmed investigation, ETA 1hr", category="reply_sent")
```

## Example prompts

```
Check my inbox
Show me unread emails from this week
Search for emails from sarah@bigclient.com
Reply to the latest email from DevOps
Draft a follow-up to the Q1 planning thread
What folders do I have?
Emails from billing@vendor.com are always URGENT
Always sign off with "Cheers,"
Show me what you know about sarah@bigclient.com
```

## Customization

### Check interval

```yaml
triggers:
  - type: cron
    schedule: "*/5 * * * *"   # every 5 minutes (default)
    timezone: UTC              # change to your timezone
```

Common schedules:
- `*/2 * * * *` -- every 2 minutes (aggressive)
- `*/15 * * * *` -- every 15 minutes (conservative)
- `0 * * * *` -- hourly
- `0 9-18 * * 1-5` -- business hours only (9am-6pm, Mon-Fri)

### Read-only mode

To disable sending entirely (triage and alerts only):

```yaml
tools:
  - type: email
    read_only: true    # removes send_email tool
    smtp_host: ""      # not needed in read-only mode
```

### Slack configuration

```yaml
tools:
  - type: slack
    webhook_url: "${SLACK_WEBHOOK_URL}"
    username: Email Agent
    icon_emoji: ":email:"
```

Remove the slack tool entry entirely to run without Slack alerts.

### Memory sizing

```yaml
memory:
  semantic:
    max_memories: 2000    # sender profiles, contact preferences
  episodic:
    max_episodes: 5000    # triage records, sent replies
  procedural:
    max_procedures: 200   # style rules, triage rules
```

### Token budget

```yaml
guardrails:
  max_tokens_per_run: 40000       # per cron tick or interactive turn
  daemon_daily_token_budget: 500000  # daily cap for daemon mode
```

### Teaching preferences

In interactive mode, tell the agent your rules:

```
Emails from billing@vendor.com are always URGENT
Always sign off with "Best regards,"
Never alert me about GitHub notifications
Emails with "invoice" in the subject are REPLY_NEEDED
```

The agent stores these as procedural memories and applies them to future triage and reply drafting.

## Changing the model

Edit `spec.model` in `role.yaml`:

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
