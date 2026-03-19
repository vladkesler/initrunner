---
name: secret-detection
description: >
  Detect hardcoded secrets, API keys, tokens, and credentials in source
  code using pattern matching. Covers AWS, GitHub, Slack, Stripe, and
  generic high-entropy strings.
---

Secret detection skill using ripgrep pattern matching.

## When to activate

Always activate this skill regardless of project language. Secrets can
appear in any file type.

## Scanner commands

Run each pattern separately via shell. Exclude lock files and
node_modules from all scans.

### AWS credentials

```
rg -n '(?i)(AKIA[0-9A-Z]{16}|aws.{0,20}secret.{0,20}['\''"][0-9a-zA-Z/+]{40})' --glob '!*.{lock,sum}' --glob '!node_modules/**'
```

### GitHub tokens

```
rg -n '(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59})' --glob '!*.{lock,sum}' --glob '!node_modules/**'
```

### Generic secrets

```
rg -n '(?i)(password|secret|api_key|apikey|token)\s*[=:]\s*['\''"][^'\''"]{8,}' --glob '*.{py,js,ts,yaml,yml,json,env,toml,cfg,ini,conf}' --glob '!node_modules/**'
```

### Private keys

```
rg -n 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' --glob '!node_modules/**'
```

## Verification

For each match:

1. Check the file path. Skip these:
   - `.env.example` files
   - Test fixtures and mock data directories
   - Documentation and README files
   - Lock files (package-lock.json, uv.lock, go.sum)

2. Check the value. Skip if it contains:
   - Placeholder strings: "xxx", "changeme", "your-", "example",
     "TODO", "REPLACE", "insert", "dummy", "fake", "test"
   - Empty strings or whitespace-only values

3. Check the context. Skip if:
   - The variable is assigned from an environment variable
     (`os.environ`, `process.env`)
   - The value is overridden by runtime config

## MUST flag

- Real AWS access keys (AKIA prefix + 16 uppercase alphanumeric chars)
- Private key blocks (BEGIN PRIVATE KEY) in source code
- Database connection strings with inline passwords
- Tokens matching known formats (ghp_, sk-live_, xoxb-) that are not
  placeholders

## MUST NOT flag

- `.env.example` files with placeholder values
- Test fixtures with fake credentials
- Documentation examples showing credential format
- Lock files (package-lock.json, uv.lock, go.sum, yarn.lock)
- Variables named "secret" or "password" assigned empty strings or
  placeholder values
- Environment variable references (`${SECRET}`, `os.getenv("SECRET")`)
