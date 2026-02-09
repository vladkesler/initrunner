# Security Policy

## Supported Versions

| Version   | Supported          |
|-----------|--------------------|
| 0.2.x     | Yes                |
| < 0.2     | No                 |

## Reporting a Vulnerability

**Do not open a public issue.** Instead, email **contact@initrunner.ai** with:

- A description of the vulnerability
- Steps to reproduce
- Affected versions
- Any suggested fix (optional)

### Response Timeline

- **Acknowledgement:** within 48 hours
- **Initial assessment:** within 1 week
- **Fix or mitigation:** varies by severity, targeting 30 days for critical issues

## Scope

The following areas are in scope:

- **Tool sandboxing** — escaping filesystem, SQL, shell, or git tool restrictions
- **Path traversal** — accessing files outside allowed directories
- **SSRF** — server-side request forgery via HTTP or web_reader tools
- **Injection** — command injection, SQL injection, prompt injection leading to tool misuse
- **Audit bypass** — circumventing the audit trail
- **Secret leakage** — sensitive environment variables exposed in outputs or logs

## Security Hardening

See [docs/security/security.md](docs/security/security.md) for the security hardening guide.
