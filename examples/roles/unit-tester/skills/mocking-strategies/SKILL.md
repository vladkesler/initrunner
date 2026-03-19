---
name: mocking-strategies
description: >
  Mock, patch, fake, and stub patterns for isolating dependencies in
  Python and JavaScript test suites.
---

Mocking strategies for isolating external dependencies in tests.

## When to activate

Use this skill when tests need to isolate external dependencies such as
databases, APIs, filesystems, time, or randomness.

## Python mocking

- `unittest.mock.patch("module.path.ClassName")` -- replace an object for
  the duration of a test. Use as a decorator or context manager.
- `patch.object(obj, "attr")` -- patch a specific attribute on a live
  object.
- `MagicMock(spec=RealClass)` -- create a mock that mirrors the real class
  API; accessing non-existent attributes raises `AttributeError`.
- `side_effect` -- set to a function for dynamic return values, or to an
  exception class to simulate errors.
- `return_value` -- set the fixed return value of the mock.
- `monkeypatch` (pytest built-in) -- set attributes, environment variables,
  or dict items for the duration of a test without import-path gymnastics.

## JavaScript mocking

- `jest.mock("module")` / `vi.mock("module")` -- auto-mock an entire
  module. Provide a factory function for custom behavior.
- Manual mocks in `__mocks__/` -- place a file next to `node_modules` or
  the real module to override it project-wide.
- Dependency injection -- pass dependencies as constructor or function
  arguments to make them trivially replaceable in tests.
- `msw` (Mock Service Worker) -- intercept HTTP at the network level for
  realistic API mocking without changing application code.

## When to mock

- External HTTP services and APIs.
- Time and dates (`datetime.now`, `Date.now`).
- Filesystem reads and writes.
- Network sockets and connections.
- Databases and data stores.
- Random number generators and entropy sources.

## When NOT to mock

- Pure functions with no side effects -- just call them directly.
- Data transformations and mapping logic.
- Simple utility functions.
- The system under test itself -- that makes the test tautological.

## Mock verification

- Python: `mock.assert_called_once_with(arg1, arg2)`,
  `mock.call_count`, `mock.call_args_list`.
- JavaScript: `expect(fn).toHaveBeenCalledTimes(1)`,
  `expect(fn).toHaveBeenCalledWith(arg1, arg2)`.

## MUST

- Mock at the module boundary -- patch where the dependency is imported,
  not where it is defined.
- Use `spec=True` (Python) so the mock rejects calls to methods that do not
  exist on the real object.
- Reset or restore mocks between tests to prevent leakage.

## MUST NOT

- Do not mock the system under test -- only mock its collaborators.
- Do not over-mock to the point where the test only verifies mock wiring
  and proves nothing about real behavior.
- Do not mock standard library builtins without a clear reason (e.g.
  mocking `open` is fine for filesystem isolation, but mocking `len` is
  not).
