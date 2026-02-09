---
name: code-tools
description: Code execution and file browsing tools. Use when the agent needs to read files or run Python code.
compatibility: Requires initrunner with filesystem and python tools
metadata:
  author: jcdenton
  version: "1.0"
  tags: code, development
# InitRunner extensions
tools:
  - type: filesystem
    root_path: "."
    read_only: true
  - type: python
    timeout_seconds: 30
    require_confirmation: true
requires:
  env: []
  bins:
    - python3
---

You have code tools available. Use read_file/list_directory to browse
the codebase and run_python to execute Python snippets.

## Guidelines

- Always read files before suggesting modifications
- Use Python execution for calculations and data processing
- Keep code snippets focused and minimal
