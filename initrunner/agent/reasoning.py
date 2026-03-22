"""Reasoning state primitives: ThinkState, TodoItem, TodoList, SpawnedTask."""

from __future__ import annotations

from dataclasses import dataclass, field

from initrunner._graph import CycleError, detect_cycle
from initrunner._ids import generate_id

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "failed", "skipped"})
_VALID_PRIORITIES = frozenset(_PRIORITY_ORDER)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped"})


# ---------------------------------------------------------------------------
# ThinkState
# ---------------------------------------------------------------------------


@dataclass
class ThinkState:
    """Accumulates agent thoughts as a numbered chain (ring buffer)."""

    thoughts: list[str] = field(default_factory=list)
    max_thoughts: int = 50

    def record(self, thought: str) -> str:
        """Append a thought, evicting the oldest if at capacity."""
        if len(self.thoughts) >= self.max_thoughts:
            self.thoughts.pop(0)
        self.thoughts.append(thought)
        return self.format()

    def format(self) -> str:
        lines = [f"  {i + 1}. {t}" for i, t in enumerate(self.thoughts)]
        return f"Thoughts ({len(self.thoughts)}):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# TodoItem + TodoList
# ---------------------------------------------------------------------------


@dataclass
class TodoItem:
    """A single actionable item with priority and dependency tracking."""

    id: str
    description: str
    status: str = "pending"
    priority: str = "medium"
    depends_on: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TodoList:
    """Priority-aware task list with dependency resolution and cycle detection."""

    items: dict[str, TodoItem] = field(default_factory=dict)
    max_items: int = 30

    def add(
        self,
        description: str,
        priority: str = "medium",
        depends_on: list[str] | None = None,
    ) -> TodoItem:
        """Create a todo item. Raises CycleError if deps form a cycle."""
        if len(self.items) >= self.max_items:
            raise ValueError(f"Todo list full ({self.max_items} items)")
        priority = priority if priority in _VALID_PRIORITIES else "medium"
        deps = depends_on or []
        for dep_id in deps:
            if dep_id not in self.items:
                raise ValueError(f"Dependency '{dep_id}' does not exist")
        item_id = generate_id(8)
        item = TodoItem(
            id=item_id,
            description=description,
            priority=priority,
            depends_on=deps,
        )
        self.items[item_id] = item
        self._check_cycles()
        return item

    def batch_add(self, items: list[dict]) -> list[TodoItem]:
        """Create multiple items. Supports inter-batch dep refs via temp IDs.

        Each dict: {description, priority?, depends_on?}.
        ``depends_on`` entries that match a 0-based index (as string) within the
        batch are resolved to the generated ID.
        """
        created: list[TodoItem] = []
        index_to_id: dict[str, str] = {}
        for i, spec in enumerate(items):
            desc = spec.get("description", "")
            if not desc:
                continue
            priority = spec.get("priority", "medium")
            raw_deps_val = spec.get("depends_on", [])
            # Normalize: LLMs may send a comma-separated string instead of a list
            if isinstance(raw_deps_val, str):
                raw_deps = [d.strip() for d in raw_deps_val.split(",") if d.strip()]
            else:
                raw_deps = list(raw_deps_val) if raw_deps_val else []
            resolved_deps: list[str] = []
            for dep in raw_deps:
                if dep in index_to_id:
                    resolved_deps.append(index_to_id[dep])
                elif dep in self.items:
                    resolved_deps.append(dep)
                else:
                    raise ValueError(f"Dependency '{dep}' not found (batch index or existing ID)")
            item = self.add(desc, priority, resolved_deps)
            index_to_id[str(i)] = item.id
            created.append(item)
        return created

    def update(self, item_id: str, **kwargs: str) -> TodoItem:
        """Update fields on an existing item."""
        item = self._get(item_id)
        if "status" in kwargs:
            status = kwargs["status"]
            if status not in _VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'")
            item.status = status
        if "priority" in kwargs:
            priority = kwargs["priority"]
            item.priority = priority if priority in _VALID_PRIORITIES else item.priority
        if "notes" in kwargs:
            item.notes = kwargs["notes"]
        if "description" in kwargs:
            item.description = kwargs["description"]
        return item

    def mark_in_progress(self, item_id: str) -> TodoItem:
        """Convenience: set status to in_progress."""
        return self.update(item_id, status="in_progress")

    def remove(self, item_id: str) -> None:
        """Remove an item and clean up dangling dep references."""
        self._get(item_id)  # validate exists
        del self.items[item_id]
        for item in self.items.values():
            item.depends_on = [d for d in item.depends_on if d != item_id]

    def get_next(self) -> TodoItem | None:
        """Return highest-priority pending item whose deps are all terminal."""
        candidates: list[TodoItem] = []
        for item in self.items.values():
            if item.status != "pending":
                continue
            if all(self._is_terminal(dep_id) for dep_id in item.depends_on):
                candidates.append(item)
        if not candidates:
            return None
        candidates.sort(key=lambda it: _PRIORITY_ORDER.get(it.priority, 2))
        return candidates[0]

    def is_all_done(self) -> bool:
        """True when every item is in a terminal status."""
        return bool(self.items) and all(
            item.status in _TERMINAL_STATUSES for item in self.items.values()
        )

    def format(self) -> str:
        """Render the todo list as a human-readable string."""
        if not self.items:
            return "(No todo items)"
        icons = {"completed": "x", "failed": "!", "skipped": "-", "in_progress": ">"}
        lines = ["Todo List:"]
        for item in self.items.values():
            icon = icons.get(item.status, " ")
            dep_str = f" (deps: {', '.join(item.depends_on)})" if item.depends_on else ""
            lines.append(
                f"  [{icon}] {item.id} [{item.priority}] {item.description} "
                f"({item.status}){dep_str}"
            )
            if item.notes:
                lines.append(f"       {item.notes}")
        return "\n".join(lines)

    def _get(self, item_id: str) -> TodoItem:
        if item_id not in self.items:
            raise ValueError(f"Todo item '{item_id}' not found")
        return self.items[item_id]

    def _is_terminal(self, item_id: str) -> bool:
        item = self.items.get(item_id)
        if item is None:
            return True  # removed dep is considered satisfied
        return item.status in _TERMINAL_STATUSES

    def _check_cycles(self) -> None:
        nodes = set(self.items)
        edges = {item_id: list(item.depends_on) for item_id, item in self.items.items()}
        try:
            detect_cycle(nodes, edges, graph_type="todo dependency")
        except CycleError:
            # Roll back the last added item (the one that caused the cycle)
            last_id = list(self.items)[-1]
            del self.items[last_id]
            raise


# ---------------------------------------------------------------------------
# SpawnedTask
# ---------------------------------------------------------------------------


@dataclass
class SpawnedTask:
    """Tracks a background agent invocation."""

    task_id: str
    agent_name: str
    prompt: str
    status: str = "running"
    result: str | None = None
    error: str | None = None
    started_at: float = 0.0
