---
name: api-contract-testing
description: >
  Curl-based HTTP endpoint probing and response validation. Tests status
  codes, response bodies, headers, and schema conformance against expected
  contracts.
requires:
  bins: [curl]
---

API contract testing skill using curl and inline validation scripts.

## When to activate

Use this skill when the project has API endpoints: an OpenAPI/Swagger spec,
a routes directory, an Express/FastAPI/Flask/Rails app entrypoint, or
existing API test files. Also activate when integration tests reference HTTP
endpoints or when a new endpoint has been added.

## Probing commands

### Status code extraction

```
curl -s -w '\n%{http_code}' http://host:port/path
```

The last line of output is the HTTP status code. Capture it separately from
the response body.

### Response body

```
curl -s http://host:port/path
```

Use `-s` (silent) to suppress progress bars.

### Timing

```
curl -s -o /dev/null -w '%{time_total}' http://host:port/path
```

Record total request time for baseline comparison.

### Sending payloads

```
curl -s -X POST -H 'Content-Type: application/json' -d '{"key":"value"}' http://host:port/path
```

Always set the Content-Type header explicitly when sending a body.

## Status validation

- **2xx** -- expected for healthy endpoints and valid requests
- **4xx** -- expected for bad input, missing auth, or not-found resources;
  verify that the status matches the specific error condition (400 for
  malformed input, 401 for missing auth, 403 for forbidden, 404 for
  unknown resource, 422 for validation failure)
- **5xx** -- indicates a bug or unhandled exception in the service; always
  flag these as failures unless explicitly expected

## Response body checks

Use inline scripts to validate JSON structure:

```
curl -s http://host:port/path | python -c "
import sys, json
data = json.load(sys.stdin)
assert 'id' in data, 'missing id field'
assert isinstance(data['id'], int), 'id must be integer'
"
```

Or with Node.js if Python is unavailable:

```
curl -s http://host:port/path | node -e "
const data = JSON.parse(require('fs').readFileSync(0,'utf8'));
if (!data.id) { console.error('missing id'); process.exit(1); }
"
```

Check:
- Required fields exist and are non-null
- Field types match expectations (string, integer, array, object)
- Array responses have expected length or are non-empty
- Nested objects have required sub-fields

## Schema validation

When an OpenAPI spec is available:

1. Identify the spec file (openapi.yaml, openapi.json, swagger.yaml).
2. Locate the schema for the endpoint's response.
3. Compare the actual response fields against the spec -- check field
   presence, types, and required/optional status.
4. Flag any extra fields not in the spec (potential data leak) and any
   missing required fields (contract violation).

## Headers

Verify these headers on every response:

- `Content-Type` -- must match expected media type (application/json for
  API endpoints)
- `CORS headers` -- Access-Control-Allow-Origin present when expected
- `Authorization-related` -- WWW-Authenticate on 401 responses
- `Cache-Control` -- appropriate caching directives for the endpoint type

## Method coverage

Test each endpoint with all relevant HTTP methods:

- **GET** -- retrieve resource, verify response structure
- **POST** -- send valid payload, verify created resource; send invalid
  payload, verify 4xx error
- **PUT** -- update existing resource, verify changes reflected
- **DELETE** -- remove resource, verify 404 on subsequent GET
- **OPTIONS** -- verify CORS preflight response when applicable

For each method, test both the success path and at least one error path.

## MUST

- Test both happy path and error responses for every endpoint
- Verify error response format is consistent across endpoints (same
  structure for all 4xx/5xx responses)
- Check auth-required endpoints return 401/403 without a token
- Validate response Content-Type header matches the actual body format
- Document the expected status code before making each request

## MUST NOT

- Modify production data -- use test/staging environments or read-only
  requests against production
- Send destructive requests (DELETE, bulk updates) without explicit
  confirmation from the user
- Hardcode auth tokens in test files -- reference environment variables
  or config files instead
- Skip error-path testing -- every endpoint needs at least one negative
  test case
- Assume JSON responses without checking Content-Type first
