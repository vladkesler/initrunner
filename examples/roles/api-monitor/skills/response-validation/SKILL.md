---
name: response-validation
description: >
  Validate API response structure and content. Detects schema drift,
  unexpected null values, and abnormal response sizes.
---

API response validation skill.

## When to activate

- When an endpoint returns 2xx but the response content looks
  unexpected (wrong content type, empty body, unusual size)
- When the user asks to validate response format or schema

## Check command

```
curl -s --max-time 10 <URL>
```

Capture the full response body for analysis.

## Checks

### 1. Content-Type

Verify the response Content-Type matches what is expected. JSON APIs
should return `application/json`. Use `-i` flag to see headers:
```
curl -s -i --max-time 10 <URL> | head -20
```

### 2. Valid JSON

If the endpoint is expected to return JSON, verify the body parses
as valid JSON. Look for HTML error pages returned instead of JSON
(common failure mode).

### 3. Expected fields

Compare the response structure against the last known structure
stored in semantic memory (category: "response_schema"). Look for:
- Missing top-level fields that were previously present
- New unexpected top-level fields (informational, not an alert)

### 4. Null values

Check for null values in fields that were previously non-null. This
can indicate upstream data pipeline failures.

### 5. Response size

Compare the response body size against the baseline from memory
(category: "response_size"). Significant deviations (>50% smaller
or >200% larger) may indicate issues.

## MUST

- Show actual vs expected values when reporting issues
- Store the response structure in semantic memory (category:
  "response_schema") for future comparison
- Store the response size baseline in semantic memory (category:
  "response_size")

## MUST NOT

- Alert on cosmetic differences (field ordering, extra whitespace)
- Alert on additional optional fields being added
- Flag response size changes for endpoints that return variable-
  length data (search results, paginated lists) without checking
  if the variance is normal
