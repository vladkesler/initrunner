---
name: email-triage
description: >
  Classify incoming emails into triage categories using content analysis,
  sender profile memory, and thread detection. Produces a category
  (URGENT, REPLY_NEEDED, FYI, NEWSLETTER, NOTIFICATION, SPAM) with
  confidence and reasoning.
---

Email triage classification skill.

## When to activate

Use this skill when processing a new email that needs to be classified
for priority and action required.

## Categories

| Category | Action | Slack alert |
|---|---|---|
| URGENT | Needs immediate attention | Individual, immediate |
| REPLY_NEEDED | Requires a response | Individual |
| FYI | Informational, no action | Batch digest (3+) |
| NEWSLETTER | Subscription content | Batch digest (3+) |
| NOTIFICATION | Automated system notice | Batch digest (3+) |
| SPAM | Unwanted, unsolicited | Never |

## Methodology

### 1. Read the email

Read the full message with `read_email`. Note:
- Subject line
- Sender (From header)
- Recipients (To/Cc -- are you the sole recipient or on a list?)
- Date
- Body content (first 500 chars are most informative)
- Thread indicators (Re:, In-Reply-To header)

### 2. Check sender profile

Recall the sender from semantic memory:
```
recall("<sender email> sender_profile")
```

If a profile exists, use it to inform classification:
- Known high-priority senders shift toward URGENT/REPLY_NEEDED
- Known newsletter senders shortcut to NEWSLETTER
- Known notification senders shortcut to NOTIFICATION

If no profile exists, create one after classification:
```
remember("<name>, <email>, first seen <date>, context: <topic>",
         category="sender_profile")
```

### 3. Content analysis

Scan the email body for signal indicators:

**URGENT signals**:
- Words: urgent, asap, immediately, critical, emergency, deadline,
  time-sensitive, action required, escalation
- Patterns: short deadline mentions ("by end of day", "within 1 hour")
- Direct address to you with a demand
- High-priority headers (X-Priority: 1)

**REPLY_NEEDED signals**:
- Direct questions (sentences ending with ?)
- Requests: "can you", "could you", "please", "would you mind"
- Meeting invitations or scheduling requests
- Approval requests
- You are the sole recipient (To, not Cc)

**FYI signals**:
- Informational tone, no questions or requests
- You are on Cc, not To
- Status updates, announcements
- Shared documents or links for reference

**NEWSLETTER signals**:
- Unsubscribe link in body or headers (List-Unsubscribe)
- Bulk sender patterns (via, on behalf of)
- Marketing language, promotional content
- Consistent recurring sender

**NOTIFICATION signals**:
- Noreply sender address
- System-generated content (build status, deploy alerts, billing)
- Structured/templated format
- Machine-generated Message-ID patterns

**SPAM signals**:
- Unknown sender with promotional/scam content
- Mismatched sender display name and email domain
- Urgency + link + credential request (phishing pattern)
- Excessive formatting, images, or tracking pixels

### 4. Thread detection

Check if the email is part of an existing thread:
- Subject starts with "Re:" or "Fwd:"
- In-Reply-To or References headers present
- Recall episodic memory for the thread topic

Thread context affects classification:
- A reply in a thread you started is likely REPLY_NEEDED
- A forwarded newsletter is FYI, not NEWSLETTER
- An escalation reply in an existing thread may be URGENT

### 5. Check procedural memory for triage rules

Recall custom triage rules:
```
recall("<sender> triage_rule")
recall("<subject keyword> triage_rule")
```

User-defined rules always override the default classification.

### 6. Assign category

Use the `think` tool to reason through the classification:
- List the signals found
- Note any sender profile context
- Note any matching triage rules
- State the category and confidence (high/medium/low)

If confidence is low, default to FYI rather than over-alerting.

## MUST

- Always check sender profile memory before classifying
- Always check for custom triage rules before finalizing
- Record every triage decision as an episodic memory
- Update sender profiles with new information from the email
- Use think to show your reasoning

## MUST NOT

- Classify without reading the email body
- Classify as URGENT based on subject line alone (read the content)
- Alert on messages already triaged (check episodic memory for the
  Message-ID)
- Follow links in suspected phishing emails
- Store email passwords or authentication tokens in memory
