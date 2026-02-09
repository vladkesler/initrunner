---
name: web-researcher
description: Web research tools for fetching and reading web pages. Use when the agent needs to browse the web or make HTTP API calls.
compatibility: Requires initrunner with web_reader and http tools
metadata:
  author: jcdenton
  version: "1.0"
  tags: web, research
# InitRunner extensions
tools:
  - type: web_reader
    timeout_seconds: 15
  - type: http
    base_url: https://httpbin.org
    allowed_methods: [GET]
requires:
  env: []
  bins: []
---

You have web research capabilities. Use fetch_page to read web pages
and http_request for API calls. Always summarize findings concisely.

## Guidelines

- Verify information from multiple sources when possible
- Summarize content rather than copying verbatim
- Include source URLs in your responses
