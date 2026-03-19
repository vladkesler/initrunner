---
name: jest-patterns
description: >
  Jest and Vitest testing patterns including describe/it blocks, expect
  matchers, mocking, and async test strategies for JavaScript and TypeScript.
requires:
  bins: [node]
---

Jest and Vitest testing patterns for JavaScript and TypeScript projects.

## When to activate

Use this skill when the project has `jest.config.*`, `vitest.config.*`,
a `package.json` listing jest or vitest as a dependency, or test files
matching `*.test.{js,ts,tsx}` or `*.spec.{js,ts,tsx}`.

## Test file structure

- Use `describe` blocks to group related tests by feature or function.
- Use `it` (or `test`) blocks for individual test cases -- each one should
  describe a single behavior.
- Nest `describe` blocks for sub-scenarios (e.g. `describe("when input is
  empty", ...)` inside `describe("parseConfig", ...)`).
- Use `beforeEach` / `afterEach` for per-test setup and teardown.
- Use `beforeAll` / `afterAll` sparingly -- only for expensive one-time
  setup like database connections.

## Matchers

- `toBe(value)` -- strict equality (`===`).
- `toEqual(value)` -- deep equality for objects and arrays.
- `toMatchObject(subset)` -- partial object matching.
- `toThrow(error?)` -- verify that a function throws.
- `toHaveBeenCalledWith(args)` -- assert mock was called with specific args.
- `toMatchSnapshot()` -- snapshot testing for serializable output.
- `toContain(item)` -- array/string includes check.
- `toHaveLength(n)` -- array or string length check.

## Mocking

- `jest.fn()` / `vi.fn()` -- create a mock function with call tracking.
- `jest.mock("module")` / `vi.mock("module")` -- replace an entire module
  with auto-mocked version.
- `jest.spyOn(obj, "method")` / `vi.spyOn(obj, "method")` -- spy on a
  method while keeping original implementation unless overridden.
- `mockResolvedValue(val)` -- shorthand for mocking async functions that
  return promises.
- `mockImplementation(fn)` -- provide a custom implementation.

## Async testing

- Use `async/await` in test functions for promise-based code.
- `.resolves` / `.rejects` matchers:
  `await expect(fetchData()).resolves.toEqual(expected)`.
- Always `await` assertions on promises -- forgetting `await` causes silent
  passes.

## Running

- `npx jest` -- run all tests.
- `npx jest --watch` -- re-run on file changes.
- `npx jest --testPathPattern="pattern"` -- filter tests by file path.
- `npx vitest` -- run vitest in watch mode.
- `npx vitest run` -- single run without watch.

## MUST

- Group related tests in `describe` blocks with clear names.
- Use meaningful test descriptions that read as specifications.
- Clean up mocks in `afterEach` (call `jest.restoreAllMocks()` or
  `vi.restoreAllMocks()`).
- Test error paths -- not just the happy path.

## MUST NOT

- Do not make real API calls -- mock HTTP with `jest.mock` or `msw`.
- Do not share mutable state between tests -- each test must be independent.
- Do not snapshot everything -- snapshots are best for serializable output
  that is tedious to assert manually, not for every return value.
