"""Load a group file and every role it references."""

from __future__ import annotations

from pathlib import Path

from initrunner.group.schema import GroupDefinition, Roster, RosterMember


class GroupLoadError(Exception):
    """Raised when a group or one of its members cannot be loaded."""


def load_group_definition(path: Path) -> GroupDefinition:
    """Read a group file without reading its members' role files."""
    from initrunner._yaml import load_raw_yaml
    from initrunner.agent.schema.adapt import AdaptError, document_to_group, run_kind_from_mapping
    from initrunner.agent.schema.document import DocumentClass, classify_mapping
    from initrunner.agent.schema.normalize import NormalizeError, normalize_mapping

    raw = load_raw_yaml(path, GroupLoadError)
    try:
        if classify_mapping(raw).document_class is not DocumentClass.FLAT_AGENT:
            raise GroupLoadError(f"{path} is not a group of agents")
        if run_kind_from_mapping(raw) != "Group":
            raise GroupLoadError(
                f"{path} is not a group of agents; a group lists members as bare "
                "'use:' references with no 'run', 'then' or 'after'"
            )
        return document_to_group(
            normalize_mapping(raw).document,
            base_dir=path.parent,
            source_path=path.resolve(),
        )
    except GroupLoadError:
        raise
    except (AdaptError, NormalizeError, ValueError, Exception) as e:
        raise GroupLoadError(f"Validation failed for {path}:\n{e}") from e


def load_group(path: Path) -> Roster:
    """Read a group file and load every member's role.

    Members load atomically: one bad member fails the whole group rather than
    starting a service that is quietly missing an agent. Every problem is
    reported at once so a broken deployment can be fixed in one pass.
    """
    from initrunner.agent.loader import load_role

    group = load_group_definition(path)

    members: dict[str, RosterMember] = {}
    failures: list[str] = []
    for key, ref in group.members.items():
        try:
            role = load_role(ref.path)
        except Exception as e:  # every failure is reported together below
            failures.append(f"  {key} ({ref.use}): {e}")
            continue
        members[key] = RosterMember(
            key=key,
            path=ref.path,
            role_dir=ref.path.parent,
            role=role,
        )

    if failures:
        joined = "\n".join(failures)
        raise GroupLoadError(f"group '{group.name}' has members that failed to load:\n{joined}")

    _reject_duplicate_role_names(group, members)
    return Roster(group=group, members=members)


def _reject_duplicate_role_names(group: GroupDefinition, members: dict[str, RosterMember]) -> None:
    """Member role names must be unique within a group.

    Audit records, daemon token budgets, default store paths and approval
    routing all key on the agent's own name, so two members sharing one would
    silently collide at runtime.
    """
    by_name: dict[str, list[str]] = {}
    for key, member in members.items():
        by_name.setdefault(member.role.metadata.name, []).append(key)

    clashes = {name: keys for name, keys in by_name.items() if len(keys) > 1}
    if not clashes:
        return

    lines = [
        f"  '{name}' is used by members {sorted(keys)}" for name, keys in sorted(clashes.items())
    ]
    joined = "\n".join(lines)
    raise GroupLoadError(
        f"group '{group.name}' has members whose roles share a name:\n{joined}\n"
        "Give each role file a unique 'name:' -- runs, budgets and stores are "
        "recorded under it."
    )
