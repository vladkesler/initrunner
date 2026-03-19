---
name: edge-case-generation
description: >
  Systematic edge-case identification including boundary values, null inputs,
  type mismatches, and error path testing.
---

Systematic edge-case generation for thorough test coverage.

## When to activate

Use this skill when generating tests for any function or module -- always
consider edge cases alongside the happy path.

## Boundary values

- Min and max integers (0, -1, `sys.maxsize`, `Number.MAX_SAFE_INTEGER`).
- Empty string `""`, single-character string `"a"`, very long strings.
- Empty collections: `[]`, `{}`, `set()`.
- Zero, negative numbers, very large numbers.
- Single-element collections -- many off-by-one bugs surface here.
- Boundary of valid ranges: if a function accepts 1--100, test 0, 1, 100,
  and 101.

## Null/None inputs

- `None` (Python) or `null`/`undefined` (JavaScript) for every parameter
  that could receive them.
- Missing dictionary or object keys.
- `null` values inside JSON payloads.
- Optional parameters omitted vs explicitly set to None/null.

## Type edge cases

- Wrong types passed to loosely-typed functions (string where int expected).
- Unicode strings with emoji, RTL characters, zero-width joiners.
- Special characters: newlines, tabs, null bytes, path separators.
- `NaN`, `Infinity`, `-Infinity` for numeric inputs.
- Very long strings (10k+ characters) to surface truncation or memory bugs.

## Error paths

- Invalid arguments that should raise/throw.
- File not found, permission denied, directory instead of file.
- Network timeout, connection refused, DNS resolution failure.
- Malformed input: invalid JSON, broken XML, truncated data.
- Division by zero, integer overflow.

## Concurrency

- Race conditions when two calls happen simultaneously (if applicable).
- Concurrent reads and writes to shared state.
- Reentrant calls -- calling a function while it is already executing.

## Methodology

For each function parameter:
1. List the valid range.
2. Test the first valid value, the last valid value, and one value just
   outside each boundary.

For each branch in the function:
1. Ensure at least one test exercises that branch.

For each exception or error the function can raise:
1. Write a test that triggers it and verifies both the type and the message.

## MUST

- Test empty inputs for every function that accepts collections or strings.
- Test the first and last valid values of every bounded parameter.
- Test error messages, not just error types -- verify the message is helpful.

## MUST NOT

- Do not generate edge cases that are unreachable given the function's type
  signature and call sites.
- Do not test implementation details -- edge cases should exercise the
  public API contract.
- Do not write brittle tests tied to exact error message wording -- use
  substring or pattern matching when messages may evolve.
