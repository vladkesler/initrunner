"""Tests for ReflectionState, TodoList, and format_reflection_state."""

from __future__ import annotations

from initrunner.agent.reasoning import TodoList
from initrunner.agent.reflection import (
    ReflectionState,
    format_reflection_state,
)


class TestReflectionState:
    def test_default_state(self):
        state = ReflectionState()
        assert state.completed is False
        assert state.summary == ""
        assert state.status == "completed"
        assert len(state.todo.items) == 0

    def test_check_auto_complete_when_all_done(self):
        state = ReflectionState()
        item = state.todo.add("Do something")
        state.todo.update(item.id, status="completed")
        state.check_auto_complete()
        assert state.completed is True

    def test_check_auto_complete_not_done(self):
        state = ReflectionState()
        state.todo.add("Do something")
        state.check_auto_complete()
        assert state.completed is False

    def test_check_auto_complete_empty_todo(self):
        state = ReflectionState()
        state.check_auto_complete()
        assert state.completed is False


class TestFormatReflectionState:
    def test_empty_state(self):
        state = ReflectionState()
        result = format_reflection_state(state)
        assert "No todo items" in result

    def test_with_items(self):
        state = ReflectionState()
        item1 = state.todo.add("Research topic")
        state.todo.update(item1.id, status="completed")
        item2 = state.todo.add("Write summary")
        state.todo.mark_in_progress(item2.id)
        state.todo.update(item2.id, notes="halfway")
        state.todo.add("Review")

        result = format_reflection_state(state)
        assert "Todo List:" in result
        assert "Research topic" in result
        assert "completed" in result
        assert "Write summary" in result
        assert "in_progress" in result
        assert "halfway" in result
        assert "Review" in result

    def test_failed_item(self):
        state = ReflectionState()
        item = state.todo.add("Step")
        state.todo.update(item.id, status="failed")
        result = format_reflection_state(state)
        assert "[!]" in result

    def test_skipped_item(self):
        state = ReflectionState()
        item = state.todo.add("Step")
        state.todo.update(item.id, status="skipped")
        result = format_reflection_state(state)
        assert "[-]" in result

    def test_budget_block_absent_when_not_autonomous(self):
        state = ReflectionState()
        result = format_reflection_state(state)
        assert "BUDGET:" not in result

    def test_budget_block_iteration_only(self):
        state = ReflectionState(iterations_completed=3, max_iterations=5)
        result = format_reflection_state(state)
        assert "BUDGET:" in result
        assert "Iteration: 3/5 (60%)" in result
        assert "Tokens:" not in result
        assert "Time:" not in result

    def test_budget_block_full(self):
        state = ReflectionState(
            iterations_completed=7,
            max_iterations=10,
            tokens_consumed=42000,
            token_budget=50000,
            elapsed_seconds=245.7,
            timeout_seconds=300,
        )
        result = format_reflection_state(state)
        assert "Iteration: 7/10 (70%)" in result
        assert "Tokens: 42,000/50,000 (84%)" in result
        assert "Time: 245s/300s (81%)" in result

    def test_budget_percentages_truncate(self):
        state = ReflectionState(iterations_completed=1, max_iterations=3)
        result = format_reflection_state(state)
        # 1/3 = 33.33...% should truncate to 33%, not round to 34%
        assert "(33%)" in result


class TestTodoList:
    def test_add_and_get(self):
        todo = TodoList()
        item = todo.add("First task")
        assert item.id in todo.items
        assert item.description == "First task"
        assert item.status == "pending"
        assert item.priority == "medium"

    def test_priority_ordering(self):
        todo = TodoList()
        todo.add("Low task", priority="low")
        todo.add("Critical task", priority="critical")
        todo.add("High task", priority="high")
        next_item = todo.get_next()
        assert next_item is not None
        assert next_item.description == "Critical task"

    def test_dependency_resolution(self):
        todo = TodoList()
        item_a = todo.add("First")
        item_b = todo.add("Second", depends_on=[item_a.id])
        # item_b should not be next because item_a is pending
        next_item = todo.get_next()
        assert next_item is not None
        assert next_item.id == item_a.id
        # Complete item_a
        todo.update(item_a.id, status="completed")
        next_item = todo.get_next()
        assert next_item is not None
        assert next_item.id == item_b.id

    def test_cycle_detection(self):
        from initrunner._graph import CycleError

        todo = TodoList()
        item_a = todo.add("A")
        item_b = todo.add("B", depends_on=[item_a.id])
        import pytest

        with pytest.raises(CycleError):
            todo.add("C", depends_on=[item_b.id])
            # Now try to create a cycle: A depends on C
            todo.items[item_a.id].depends_on = [todo.items[list(todo.items.keys())[-1]].id]
            todo._check_cycles()

    def test_batch_add(self):
        todo = TodoList()
        items = todo.batch_add(
            [
                {"description": "Step 1"},
                {"description": "Step 2", "depends_on": ["0"]},
                {"description": "Step 3", "priority": "high"},
            ]
        )
        assert len(items) == 3
        assert items[0].id in items[1].depends_on

    def test_is_all_done(self):
        todo = TodoList()
        item = todo.add("Task")
        assert not todo.is_all_done()
        todo.update(item.id, status="completed")
        assert todo.is_all_done()

    def test_mark_in_progress(self):
        todo = TodoList()
        item = todo.add("Task")
        updated = todo.mark_in_progress(item.id)
        assert updated.status == "in_progress"

    def test_remove_cleans_deps(self):
        todo = TodoList()
        item_a = todo.add("A")
        item_b = todo.add("B", depends_on=[item_a.id])
        todo.remove(item_a.id)
        assert item_a.id not in todo.items
        assert todo.items[item_b.id].depends_on == []

    def test_max_items_enforced(self):
        import pytest

        todo = TodoList(max_items=2)
        todo.add("One")
        todo.add("Two")
        with pytest.raises(ValueError, match="full"):
            todo.add("Three")

    def test_invalid_dependency(self):
        import pytest

        todo = TodoList()
        with pytest.raises(ValueError, match="does not exist"):
            todo.add("Task", depends_on=["nonexistent"])

    def test_format(self):
        todo = TodoList()
        item = todo.add("Task", priority="high")
        result = todo.format()
        assert "Todo List:" in result
        assert item.id in result
        assert "high" in result
        assert "Task" in result
