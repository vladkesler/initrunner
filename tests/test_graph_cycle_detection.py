"""Cycle detection with loop-back allow_edges (initrunner/_graph.py)."""

from __future__ import annotations

import pytest

from initrunner._graph import CycleError, detect_cycle, topological_tiers


class TestTopologicalTiersAllowEdges:
    def test_allow_edges_permits_marked_back_edge(self):
        """A marked back-edge is dropped from the in-degree calc, so no cycle."""
        nodes = {"a", "b"}
        edges = {"a": ["b"], "b": ["a"]}  # a depends on b, b depends on a
        allow_edges = {"b": {"a"}}  # exempt the b->a dependency edge

        tiers = topological_tiers(nodes, edges, allow_edges=allow_edges)
        flat = [n for tier in tiers for n in tier]
        assert set(flat) == nodes
        # b's only dependency (a) was exempted, so b is a root.
        assert "b" in tiers[0]

    def test_none_allow_edges_is_default(self):
        nodes = {"a", "b"}
        edges = {"a": ["b"]}
        tiers = topological_tiers(nodes, edges)
        assert tiers[0] == ["b"]
        assert tiers[1] == ["a"]


class TestDetectCycleAllowEdges:
    def test_unmarked_cycle_still_rejected(self):
        nodes = {"a", "b"}
        edges = {"a": ["b"], "b": ["a"]}
        with pytest.raises(CycleError, match="cycle"):
            detect_cycle(nodes, edges, "delegate", allow_edges={})

    def test_marked_back_edge_passes(self):
        nodes = {"a", "b"}
        edges = {"a": ["b"], "b": ["a"]}
        # Exempt the b->a dependency edge; should not raise.
        detect_cycle(nodes, edges, "delegate", allow_edges={"b": {"a"}})

    def test_wrong_exemption_does_not_break_three_cycle(self):
        """Exempting an edge outside the cycle leaves the 3-cycle intact."""
        nodes = {"a", "b", "c", "d"}
        # a->b->c->a is a 3-cycle; d->a is an acyclic edge we exempt.
        edges = {"a": ["c"], "c": ["b"], "b": ["a"], "d": ["a"]}
        with pytest.raises(CycleError):
            detect_cycle(nodes, edges, "delegate", allow_edges={"d": {"a"}})

    def test_exempting_one_cycle_edge_breaks_three_cycle(self):
        """Exempting any single edge of a 3-cycle makes it acyclic."""
        nodes = {"a", "b", "c"}
        edges = {"a": ["c"], "c": ["b"], "b": ["a"]}
        detect_cycle(nodes, edges, "delegate", allow_edges={"b": {"a"}})

    def test_unrelated_cycle_rejected_despite_allowed_edge(self):
        """A whitelisted edge does not mask an unrelated cycle elsewhere."""
        nodes = {"a", "b", "c", "d"}
        # b->a marked back-edge (allowed); c<->d is a separate unmarked cycle.
        edges = {"a": ["b"], "b": ["a"], "c": ["d"], "d": ["c"]}
        with pytest.raises(CycleError):
            detect_cycle(nodes, edges, "delegate", allow_edges={"b": {"a"}})
