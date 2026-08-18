"""Inventory of code that *writes* agent/team/flow YAML.

Phase 0 contract: every writer must flip in the same release as examples and
docs. This list is the checklist; the test asserts each path still exists so
renames cannot silently drop a producer.
"""

from __future__ import annotations

# (package-relative path, what it writes)
YAML_PRODUCERS: tuple[tuple[str, str], ...] = (
    ("initrunner/templates.py", "initrunner new templates"),
    ("initrunner/role_generator.py", "LLM role generator prompts"),
    ("initrunner/services/agent_builder.py", "builder / offline new"),
    ("initrunner/services/team_builder.py", "team scaffold"),
    ("initrunner/services/flow.py", "flow new scaffold"),
    ("initrunner/services/roles.py", "role defaults / save"),
    ("initrunner/services/providers.py", "provider-built RoleDefinition"),
    ("initrunner/services/agent_spec_import.py", "PydanticAI Agent Spec import"),
    ("initrunner/services/discovery.py", "directory scan keyed on apiVersion"),
    ("initrunner/dashboard/routers/builder.py", "dashboard builder save"),
    ("initrunner/cli/_helpers/_resolve.py", "directory resolve keyed on apiVersion/kind"),
    ("initrunner/packaging/bundle.py", "OCI bundle include from metadata.bundle"),
)
