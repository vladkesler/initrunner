---
name: ssl-certificate
description: >
  Check SSL/TLS certificate expiry and chain validity using openssl.
  Alerts on certificates expiring within 30 days.
requires:
  bins: [openssl]
---

SSL/TLS certificate checking skill.

## When to activate

- When the user asks about SSL or certificate status
- As a periodic deep check (check memory for last SSL check date --
  run at most once per week per endpoint)

## Check command

```
echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -dates -subject -issuer
```

Replace `<host>` with the hostname extracted from the endpoint URL
(strip the protocol and path).

## Parsing output

The command returns:
- `notBefore=` -- certificate start date
- `notAfter=` -- certificate expiry date
- `subject=` -- certificate subject (CN and/or SAN)
- `issuer=` -- certificate issuer (CA name)

Calculate days until expiry from the `notAfter` date using the current
timestamp from datetime.

## Alert thresholds

| Days remaining | Severity |
|---------------|----------|
| > 30 | No alert |
| 14-30 | Warning |
| 7-14 | Warning (urgent) |
| 1-7 | Critical |
| 0 or expired | Critical (emergency) |

## Additional checks

- **Subject match**: Verify the CN or SAN matches the hostname being
  checked. Mismatches indicate a misconfigured certificate.
- **Issuer**: Check if the issuer is a recognized CA. Self-signed
  certificates in production are a finding.

## MUST

- Include the exact expiry date and days remaining in the alert
- Include the hostname checked and the issuer name
- Store the SSL check result in semantic memory with category
  "ssl_check" to avoid redundant checks

## MUST NOT

- Alert on self-signed certificates for staging/dev URLs (check if
  the URL contains "staging", "dev", "local", "localhost", "test")
- Run SSL checks more than once per week per endpoint (check memory
  first)
