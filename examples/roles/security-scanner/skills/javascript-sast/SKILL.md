---
name: javascript-sast
description: >
  JavaScript and Node.js security scanning. Checks dependency
  vulnerabilities via npm audit and source patterns for XSS, eval, and
  prototype pollution.
requires:
  bins: [node]
---

JavaScript and Node.js security scanning skill.

## When to activate

Use this skill when the repository contains package.json or
package-lock.json.

## Scanner commands

### Dependency audit

```
npm audit --json 2>/dev/null
```

Returns advisories with severity, module_name, title, url, and
findings[].paths showing which dependencies pull in the vulnerable
package.

### Source pattern scan

```
rg -n 'eval\(|innerHTML\s*=|dangerouslySetInnerHTML|document\.write\(' \
  --glob '*.{js,ts,jsx,tsx}' \
  --glob '!node_modules/**' \
  --glob '!*.test.*' \
  --glob '!*.spec.*'
```

## Parsing npm audit output

The JSON output contains an `advisories` object keyed by advisory ID.
Each advisory has:
- `severity` -- critical, high, moderate, low
- `module_name` -- the vulnerable package
- `title` -- vulnerability description
- `url` -- link to the advisory
- `findings[].paths` -- dependency paths that include this package

Focus on production dependencies. Skip devDependency-only findings.

## Verification

For source pattern matches, read 10-15 lines of surrounding context:

1. Is the argument to eval() a variable or a constant string?
2. Is innerHTML assigned from user input, URL params, or API response?
3. Is there DOMPurify or other sanitization before the assignment?
4. For prototype pollution: is there a recursive merge without
   hasOwnProperty check on user-supplied objects?

## MUST flag

- `eval()` with variables (not constant strings)
- `innerHTML` assigned from user input, URL params, or API response
  without sanitization
- Prototype pollution patterns (recursive merge without hasOwnProperty)
- Missing CSRF protection on state-changing routes
- Production dependency advisories with severity high or critical

## MUST NOT flag

- `eval` in build configs (webpack.config.js, babel.config.js,
  jest.config.js, vite.config.ts)
- `innerHTML` with DOMPurify-sanitized content
- `dangerouslySetInnerHTML` with compile-time constants
- devDependency-only audit findings (not in production bundle)
- Test and spec files
