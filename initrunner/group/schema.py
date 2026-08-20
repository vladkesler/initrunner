"""Group definition and loaded roster.

Internal data, so these are dataclasses rather than Pydantic models: the public
schema is ``AgentDocument`` and the validation lives there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.observability import ObservabilityConfig
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.schema.security import SecurityPolicy
    from initrunner.flow.schema import SharedMemoryConfig
    from initrunner.team.schema import TeamDocumentsConfig


@dataclass(frozen=True)
class GroupMemberRef:
    """One declared member, before its role file is read."""

    key: str
    use: str
    path: Path


@dataclass(frozen=True)
class GroupDefinition:
    """A group file, adapted but not yet loaded.

    Member roles are deliberately not read here so that ``validate`` can report
    problems per member instead of failing on the first bad reference.
    """

    name: str
    members: dict[str, GroupMemberRef]
    shared_memory: SharedMemoryConfig
    shared_documents: TeamDocumentsConfig
    security: SecurityPolicy
    observability: ObservabilityConfig | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    author: str = ""
    version: str = ""
    dependencies: tuple[str, ...] = ()
    source_path: Path | None = None

    @property
    def source_dir(self) -> Path:
        """Directory shared paths resolve against.

        For a group file that is the directory holding it; a directory group's
        ``source_path`` is the directory itself.
        """
        if self.source_path is None:
            return Path.cwd()
        return self.source_path if self.source_path.is_dir() else self.source_path.parent


@dataclass(frozen=True)
class RosterMember:
    """A member whose role file has been read."""

    key: str
    path: Path
    role_dir: Path
    role: RoleDefinition


@dataclass
class Roster:
    """A group with every member's role loaded."""

    group: GroupDefinition
    members: dict[str, RosterMember] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.group.name

    def keys(self) -> list[str]:
        return list(self.members)
