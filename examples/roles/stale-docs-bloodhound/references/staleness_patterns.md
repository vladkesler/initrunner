# Documentation Staleness Patterns

Human-readable reference for the 10 most common ways documentation falls out of sync with source code. This file is bundled for convenience -- the agent has these patterns inlined in its system prompt and does not read this file at runtime.

---

## 1. Renamed Identifiers

**Pattern**: A function, class, variable, CLI command, or module is renamed in code but the old name persists in documentation.

**What to look for in diffs**: `-def old_name` / `+def new_name`, renamed imports, renamed CLI subcommands.

**Where docs break**: API references, tutorials with code examples, CLI usage sections, import examples.

**Severity**: Incorrect (docs show a name that no longer exists).

---

## 2. Changed Function Signatures

**Pattern**: Parameters added, removed, reordered, or type-changed. Documentation shows the old call signature.

**What to look for in diffs**: Changed `def` lines, new/removed keyword arguments, changed type annotations.

**Where docs break**: API references, code examples, parameter tables, docstring mirrors in external docs.

**Severity**: Incorrect to breaking (callers following docs will get TypeError).

---

## 3. Changed Default Values

**Pattern**: A config key, flag, or function parameter default is changed in code but docs still state the old default.

**What to look for in diffs**: `default=old` to `default=new`, changed YAML/TOML defaults, changed argparse defaults.

**Where docs break**: Configuration references, "getting started" guides, parameter tables.

**Severity**: Incorrect (users expect behavior that no longer matches).

---

## 4. Removed Features

**Pattern**: An entire feature, flag, endpoint, or configuration option is removed. Documentation still describes it as available.

**What to look for in diffs**: Deleted functions, removed CLI flags, deleted route handlers, removed config keys.

**Where docs break**: Feature lists, configuration guides, API references, changelog (if not updated).

**Severity**: Breaking (users will try to use something that doesn't exist).

---

## 5. Undocumented New Features

**Pattern**: A new public API, CLI flag, config key, or endpoint is added with no corresponding documentation.

**What to look for in diffs**: New `def` with public names, new argparse arguments, new route handlers, new config keys.

**Where docs break**: Feature is absent from docs entirely. Look for the new identifier -- its absence is the staleness signal.

**Severity**: Incomplete (users don't know the feature exists).

---

## 6. Changed Error Messages

**Pattern**: Error text is changed in code but troubleshooting guides or FAQ docs reference the old message.

**What to look for in diffs**: Changed string literals in `raise`, `log.error`, `fmt.Errorf`, or similar.

**Where docs break**: Troubleshooting sections, FAQ, error code references.

**Severity**: Incorrect (users can't find their error in the docs).

---

## 7. Changed Dependencies

**Pattern**: A required package, minimum version, or system dependency is changed. Installation docs are wrong.

**What to look for in diffs**: Changed `requirements.txt`, `pyproject.toml` dependencies, `package.json`, `go.mod`, Dockerfile base images.

**Where docs break**: Installation guides, prerequisites sections, Dockerfile examples.

**Severity**: Breaking (install instructions fail) to incorrect (version mismatch warnings).

---

## 8. Changed Config Structure

**Pattern**: Config file format, nesting, or key names changed. Configuration docs show the old structure.

**What to look for in diffs**: Renamed config keys, changed nesting depth, new required keys, schema changes.

**Where docs break**: Configuration reference, example config files in docs, migration guides.

**Severity**: Breaking (old config files won't parse) to incorrect (wrong key names).

---

## 9. Changed API Responses

**Pattern**: Response fields added, removed, renamed, or type-changed. API docs show the old response shape.

**What to look for in diffs**: Changed response serialization, renamed fields in response models, added/removed fields.

**Where docs break**: API reference, response examples, client integration guides.

**Severity**: Incorrect (clients parsing responses based on docs will break).

---

## 10. Moved or Reorganized Code

**Pattern**: File paths, import paths, or module structure changed. Docs reference old paths.

**What to look for in diffs**: File renames/moves, changed `__init__.py` exports, reorganized package structure.

**Where docs break**: Import examples, file path references, architecture diagrams, "project structure" sections.

**Severity**: Incorrect (imports or file references in docs won't work).

---

## Quick Reference

| # | Pattern | Grep Target | Typical Doc Location | Severity |
|---|---------|-------------|---------------------|----------|
| 1 | Renamed identifiers | Old function/class/var names | API refs, tutorials | Incorrect |
| 2 | Changed signatures | Function name + old params | API refs, examples | Incorrect-Breaking |
| 3 | Changed defaults | Config key + old default value | Config guides | Incorrect |
| 4 | Removed features | Removed function/flag/endpoint | Feature lists, config | Breaking |
| 5 | Undocumented features | New identifier (absence) | All docs | Incomplete |
| 6 | Changed errors | Old error string phrases | Troubleshooting, FAQ | Incorrect |
| 7 | Changed dependencies | Package names, versions | Install guides | Breaking |
| 8 | Changed config | Old config key paths | Config reference | Breaking |
| 9 | Changed API responses | Old field names | API docs | Incorrect |
| 10 | Moved code | Old file/import paths | Architecture docs | Incorrect |
