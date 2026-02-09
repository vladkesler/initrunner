"""Shared topological sort using Kahn's algorithm with O(1) deque operations."""

from __future__ import annotations

from collections import defaultdict, deque


class CycleError(ValueError):
    """Raised when a cycle is detected in a directed graph."""


def topological_tiers(
    nodes: set[str],
    edges: dict[str, list[str]],
) -> list[list[str]]:
    """Return nodes grouped into topological tiers using Kahn's algorithm.

    Args:
        nodes: All node names.
        edges: Mapping from node → list of nodes it depends on.
               (i.e. edges[A] = [B, C] means A depends on B and C)

    Returns:
        List of tiers. Each tier contains nodes that can be processed in
        parallel (all dependencies are in earlier tiers).

    Raises:
        CycleError: If the graph contains a cycle.
    """
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    dependents: dict[str, list[str]] = defaultdict(list)

    for node, deps in edges.items():
        for dep in deps:
            in_degree[node] += 1
            dependents[dep].append(node)

    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    tiers: list[list[str]] = []

    while queue:
        tier = sorted(queue)
        tiers.append(tier)
        queue.clear()
        for node in tier:
            for child in dependents[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    visited = sum(len(t) for t in tiers)
    if visited != len(nodes):
        raise CycleError("Graph contains a cycle")

    return tiers


def detect_cycle(
    nodes: set[str],
    edges: dict[str, list[str]],
    graph_type: str = "dependency",
) -> None:
    """Raise CycleError if the graph has a cycle.

    Same as topological_tiers but only checks for cycles, discarding the tier
    result. Provides a descriptive error message including the graph_type.

    Args:
        nodes: All node names.
        edges: Mapping from node → list of nodes it depends on.
        graph_type: Human-readable label for error messages (e.g. "delegate", "dependency").
    """
    try:
        topological_tiers(nodes, edges)
    except CycleError:
        raise CycleError(f"Graph contains a {graph_type} cycle") from None
