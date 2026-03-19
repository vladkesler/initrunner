---
name: environment-diagnostics
description: >
  Environment variable validation and configuration verification. Checks
  that required variables are set, config files parse correctly, ports are
  available, and system dependencies meet version requirements.
requires:
  bins: []
---

Environment diagnostics skill for validating configuration and system state.

## When to activate

Use this skill when tests fail with configuration or environment errors,
when setting up a new development or staging environment, when a deployment
fails with missing config or dependency issues, or when onboarding a new
developer who needs to verify their local setup.

## Environment variables

Check that required variables are set and non-empty:

```
python -c "
import os, sys
required = ['DATABASE_URL', 'API_KEY', 'SECRET_KEY']
missing = [v for v in required if not os.environ.get(v)]
if missing:
    print('Missing or empty:', ', '.join(missing))
    sys.exit(1)
print('All required variables present')
"
```

Common patterns to check:
- **DATABASE_URL** -- connection string for the primary database
- **API_KEY / API_SECRET** -- external service credentials
- **SECRET_KEY / JWT_SECRET** -- application signing keys
- **REDIS_URL / CACHE_URL** -- cache connection strings
- **LOG_LEVEL** -- logging configuration
- **NODE_ENV / FLASK_ENV / RAILS_ENV** -- runtime environment designation

For each variable, verify not just presence but also basic format validity
(e.g., DATABASE_URL starts with a known scheme like postgres:// or mysql://).

## Config files

Verify expected configuration files exist and parse correctly:

1. **Existence** -- check that each expected config file is present.
2. **Syntax** -- attempt to parse the file in its format:

```
python -c "import json; json.load(open('config.json'))"      # JSON
python -c "import yaml; yaml.safe_load(open('config.yaml'))"  # YAML
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"  # TOML
```

3. **Required fields** -- after parsing, verify that mandatory keys exist
   in the config structure.
4. **Value validation** -- check that numeric values are in expected ranges,
   URLs are well-formed, and enum values match allowed options.

## Port conflicts

Check if expected ports are available or already bound:

```
ss -tlnp | grep :<port>
```

If a port is in use, report which process holds it:

```
ss -tlnp | grep :8000
# or
lsof -i :<port> 2>/dev/null
```

Common ports to check: 3000, 5000, 8000, 8080 (web), 5432 (PostgreSQL),
3306 (MySQL), 6379 (Redis), 27017 (MongoDB).

## Dependency versions

Check that required tools are installed and meet minimum version
requirements:

```
python --version 2>&1
node --version 2>&1
npm --version 2>&1
docker --version 2>&1
docker-compose --version 2>&1
git --version 2>&1
```

Compare against version requirements from the project's documentation or
configuration (e.g., `engines` in package.json, `python_requires` in
pyproject.toml).

Report each dependency as: installed (with version), missing, or below
minimum required version.

## Filesystem checks

- **Data directories** -- verify expected directories exist and are writable:

```
test -d /path/to/data && test -w /path/to/data && echo "OK" || echo "FAIL"
```

- **Disk space** -- check available space on relevant partitions:

```
df -h /path/to/data
```

- **Temp directory** -- verify the temp directory is writable:

```
python -c "import tempfile; f = tempfile.NamedTemporaryFile(); print(f.name); f.close()"
```

- **File permissions** -- check that config files are not world-readable
  if they contain secrets.

## Network

- **DNS resolution** -- verify that hostnames resolve:

```
python -c "import socket; print(socket.getaddrinfo('hostname', None)[0][4])"
```

- **External reachability** -- check if external services are reachable:

```
curl -s -o /dev/null -w '%{http_code}' --max-time 5 https://api.example.com/health
```

- **Proxy configuration** -- if HTTP_PROXY or HTTPS_PROXY is set, verify
  the proxy is reachable.

## MUST

- Mask sensitive values -- show only the first 4 and last 4 characters of
  secrets (e.g., `API_KEY=sk-t...xY9z`); for values shorter than 12
  characters, show only `****`
- Report all missing requirements at once -- collect every issue into a
  single summary rather than stopping at the first failure
- Suggest a fix for each issue found (e.g., "DATABASE_URL is not set --
  add it to your .env file or export it in your shell")
- Group findings by category (environment variables, config files, ports,
  dependencies, filesystem, network) for readable output
- Check the .env file (if present) for variables that might override
  system environment

## MUST NOT

- Print full secret values -- always mask credentials, tokens, and keys
- Modify environment variables, config files, or system state -- diagnostics
  are read-only
- Assume any specific operating system -- check for tool availability
  before using OS-specific commands
- Fail silently when a check cannot run -- if a tool is missing, report
  that the check was skipped and why
- Install or upgrade dependencies automatically -- only report what needs
  to change
