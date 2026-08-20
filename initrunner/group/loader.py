"""Load a group -- a group file, or a directory of agents -- and every role in it."""

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


def load_roster(path: Path) -> Roster:
    """Load a group from a group file or from a directory of agent files."""
    if path.is_dir():
        return load_directory_group(path)
    return load_group(path)


def load_group(path: Path) -> Roster:
    """Read a group file and load every member's role.

    Members load atomically: one bad member fails the whole group rather than
    starting a service that is quietly missing an agent. Every problem is
    reported at once so a broken deployment can be fixed in one pass.
    """
    group = load_group_definition(path)

    members, failures = _load_member_roles(
        (key, ref.path, f"{key} ({ref.use})") for key, ref in group.members.items()
    )
    if failures:
        joined = "\n".join(failures)
        raise GroupLoadError(f"group '{group.name}' has members that failed to load:\n{joined}")

    _reject_duplicate_role_names(group.name, members, label=lambda m: repr(m.key))
    return Roster(group=group, members=members)


def load_directory_group(directory: Path) -> Roster:
    """Read every agent file directly inside *directory* as one group.

    Members are keyed by their role's own name, which is the model ID a single
    agent already gets from ``--serve``, so moving an agent into a directory
    does not change how it is addressed.

    The group carries no shared stores and no group-level observability: a
    directory says which agents ship together and nothing more. Anything that
    needs shared memory, shared documents or listener security wants a real
    group file.
    """
    from initrunner.agent.schema.security import SecurityPolicy
    from initrunner.flow.schema import SharedMemoryConfig
    from initrunner.services.discovery import top_level_documents, unreadable_yaml_files
    from initrunner.team.schema import TeamDocumentsConfig

    resolved = directory.resolve()
    paths = top_level_documents(directory)
    if not paths:
        raise GroupLoadError(f"no agent YAML files in {directory}")

    group = GroupDefinition(
        name=resolved.name,
        members={},
        shared_memory=SharedMemoryConfig(),
        shared_documents=TeamDocumentsConfig(),
        security=SecurityPolicy(),
        source_path=resolved,
    )

    # Keyed by file name until the role is read; the real key is the role's
    # name, which only exists once the file parses.
    members, failures = _load_member_roles((p.name, p, p.name) for p in paths)
    # A file that does not parse cannot be classified, so an agent among them
    # would drop out of the group in silence -- exactly the "service quietly
    # missing an agent" this loader exists to prevent. Whether the file was
    # meant to be an agent is unknowable precisely because it does not parse,
    # so it is reported as unreadable YAML rather than as a failed member.
    unreadable = [
        f"  {path.name}: does not parse as YAML: {reason}"
        for path, reason in unreadable_yaml_files(directory)
    ]
    if unreadable or failures:
        joined = "\n".join(unreadable + failures)
        raise GroupLoadError(f"directory '{directory}' could not be loaded as a group:\n{joined}")

    _reject_duplicate_role_names(
        str(directory), members, label=lambda m: str(m.path), directory=True
    )
    by_name = {
        member.role.metadata.name: RosterMember(
            key=member.role.metadata.name,
            path=member.path,
            role_dir=member.role_dir,
            role=member.role,
        )
        for member in members.values()
    }
    return Roster(group=group, members=by_name)


def _load_member_roles(items) -> tuple[dict[str, RosterMember], list[str]]:
    """Load each ``(key, path, label)`` role, collecting failures instead of raising."""
    from initrunner.agent.loader import load_role

    members: dict[str, RosterMember] = {}
    failures: list[str] = []
    for key, path, label in items:
        try:
            role = load_role(path)
        except Exception as e:  # every failure is reported together by the caller
            failures.append(f"  {label}: {e}")
            continue
        members[key] = RosterMember(key=key, path=path, role_dir=path.parent, role=role)
    return members, failures


def _reject_duplicate_role_names(
    group_name: str,
    members: dict[str, RosterMember],
    *,
    label,
    directory: bool = False,
) -> None:
    """Member role names must be unique within a group.

    Audit records, daemon token budgets, default store paths and approval
    routing all key on the agent's own name, so two members sharing one would
    silently collide at runtime.
    """
    by_name: dict[str, list[str]] = {}
    for member in members.values():
        by_name.setdefault(member.role.metadata.name, []).append(label(member))

    clashes = {name: labels for name, labels in by_name.items() if len(labels) > 1}
    if not clashes:
        return

    lines = [
        f"  '{name}' is used by {', '.join(sorted(labels))}"
        for name, labels in sorted(clashes.items())
    ]
    joined = "\n".join(lines)
    what = "directory" if directory else "group"
    raise GroupLoadError(
        f"{what} '{group_name}' has agents that share a name:\n{joined}\n"
        "Give each role file a unique 'name:' -- runs, budgets and stores are "
        "recorded under it."
    )
