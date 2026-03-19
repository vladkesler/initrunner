---
name: reply-composer
description: >
  Draft context-aware email replies that match sender tone, reference
  thread history, and follow the user's style preferences. Presents
  drafts for review before sending.
---

Email reply composition skill.

## When to activate

Use this skill when the user asks to reply to an email, draft a
response, or compose a new message.

## Process

### 1. Gather context

Collect everything needed before writing:
- Read the original email with `read_email`
- If it's a thread, search for earlier messages in the thread:
  `search_inbox(query='SUBJECT "<thread subject>"')`
- Recall the sender profile from semantic memory
- Recall any style rules from procedural memory:
  `recall("style_rule")`
- Recall any previous replies to this sender:
  `recall("<sender> reply_sent")`

### 2. Analyze tone

Determine the appropriate tone from the original message:

| Original tone | Reply tone | Indicators |
|---|---|---|
| Formal | Formal | Full sentences, titles, "Dear", "Sincerely" |
| Semi-formal | Semi-formal | Professional but relaxed, first names, "Thanks" |
| Casual | Casual | Short sentences, contractions, emoji, "Hey" |
| Terse | Match length | One-liners, bullet points, no greeting |

Adapt to the sender's style. If the sender writes two-sentence
emails, don't reply with five paragraphs.

### 3. Research if needed

If the reply requires information you don't have:
- Use `search` to look up facts, documentation, or context
- Use `web_reader` to read referenced URLs from the original email
- Recall topic context from semantic memory

### 4. Compose draft

Write the reply following these rules:

**Structure**:
- Greeting (match sender's style)
- Acknowledge their message (one sentence, reference specifics)
- Body (answer questions, provide information, address requests)
- Next steps or call to action (if applicable)
- Sign-off (check procedural memory for preferred sign-off)

**Thread-aware replies**:
- Reference specific points from the thread, not just the last message
- Don't repeat information already established in the thread
- If the thread has multiple participants, address the relevant ones

**Length**:
- Match the expected length to the complexity of the response
- Simple confirmations: 1-2 sentences
- Detailed answers: structured with bullet points or numbered lists
- Keep under 300 words unless the topic requires more

### 5. Present for review

Show the draft to the user in this format:

```
Draft reply to: <sender name> <<sender email>>
Subject: Re: <original subject>
---

<draft body>

---
Send this reply? (yes / edit / cancel)
```

Wait for the user's response:
- **yes**: send the email using `send_email` with the `reply_to`
  parameter set to the original Message-ID
- **edit**: ask what to change, revise, and present again
- **cancel**: discard the draft

### 6. Record and learn

After sending:
- Record the reply in episodic memory:
  `record_episode(content="Replied to <sender> re: <subject> -- <brief summary>",
                  category="reply_sent")`
- If the user edited the draft, note what they changed and consider
  learning a style rule:
  `learn_procedure(content="<what the user prefers>",
                   category="style_rule")`

## MUST

- Always present the full draft before sending
- Always set the reply_to parameter when replying to maintain threading
- Always check for style rules in procedural memory before drafting
- Include Cc recipients from the original if it was a group thread

## MUST NOT

- Send an email without explicit user confirmation
- Fabricate information -- if you don't know, say so in the draft
- Change the subject line of a thread reply (breaks threading)
- Reply-all when the user only said "reply" (ask if unclear)
- Include confidential information from memory in the reply without
  checking with the user
