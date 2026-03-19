---
name: python-sast
description: >
  Python static analysis using bandit. Identifies injection, deserialization,
  unsafe exec/eval, weak crypto, and hardcoded credentials in Python code.
requires:
  bins: [bandit]
---

Python static analysis skill using bandit.

## When to activate

Use this skill when the repository contains Python code: pyproject.toml,
setup.py, requirements.txt, or .py files in the source tree.

## Scanner command

```
bandit -r . -f json -ll --exclude .venv,tests,node_modules
```

The `-ll` flag filters to medium and higher confidence. The `-f json` flag
returns structured output for parsing.

## Parsing output

Bandit JSON output has a `results` array. Each result contains:
- `filename` -- path to the file
- `line_number` -- line of the finding
- `issue_severity` -- HIGH, MEDIUM, LOW
- `issue_confidence` -- HIGH, MEDIUM, LOW
- `issue_text` -- description of the issue
- `test_id` -- bandit test identifier (e.g. B301)

## Key test IDs

| Test ID | Category |
|---------|----------|
| B101 | assert used (usually test-only) |
| B102 | exec() used |
| B301-B324 | Deserialization, SQL injection, unsafe YAML |
| B501-B507 | SSL/TLS issues |
| B601-B612 | Shell injection, subprocess |

## Verification steps

For each finding:

1. Read 10 lines of context around the flagged line using read_file.
2. Trace backwards: where does the input come from? Follow the variable
   to its source (function parameter, request object, file read, etc.).
3. If the input comes from user/network input (request.args, sys.argv,
   file read, socket, etc.), classify as HIGH confidence.
4. If the input comes from a constant, config file, or environment
   variable, classify as MEDIUM or skip.

## MUST flag

- `eval()` or `exec()` with non-constant arguments
- `pickle.loads()` on network or file input
- `yaml.load()` without `Loader=SafeLoader`
- `subprocess` with `shell=True` and string formatting (`f""`, `.format()`, `%`)
- SQL queries with f-strings or `.format()` using external input

## MUST NOT flag

- `assert` statements in test files (B101)
- Binding to `0.0.0.0` in development configs
- `hashlib` used for checksums (not security hashing)
- `subprocess` with `shell=True` and hardcoded constant strings
- `random` module used for non-security purposes (shuffling, sampling)
