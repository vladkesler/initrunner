"""Grouped agents: independent agents deployed and served together.

A group file lists existing role files and nothing else. It is a deployment
manifest, not an orchestration: members never hand off to each other, and each
one runs exactly as it would on its own.
"""

from initrunner.group.schema import GroupDefinition, GroupMemberRef, Roster, RosterMember

__all__ = [
    "GroupDefinition",
    "GroupMemberRef",
    "Roster",
    "RosterMember",
]
