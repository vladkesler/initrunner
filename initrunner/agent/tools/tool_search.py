"""Tool search meta-tool — BM25 keyword search over the tool catalog.

When agents have many configured tools (10+), tool definitions consume massive
context and model tool-selection accuracy degrades.  This module provides a
``search_tools`` meta-tool that lets the agent discover tools on demand, using
PydanticAI's ``prepare_tools`` callback to dynamically filter which tools the
model sees at each inference step.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic_ai.toolsets.function import FunctionToolset

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.tools import ToolDefinition


# ---------------------------------------------------------------------------
# Stopwords stripped during tokenisation (common English words that add noise)
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    "a an and are as at be by for from has have in is it of on or the to with".split()
)

# ---------------------------------------------------------------------------
# BM25 keyword index
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Tokenize text: expand snake/camelCase, lowercase, split on non-alphanumeric."""
    # Expand camelCase boundaries BEFORE lowering: "sendSlackMessage" → "send Slack Message"
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.lower()
    # Split on non-alphanumeric (handles snake_case, hyphens, etc.)
    tokens = re.split(r"[^a-z0-9]+", text)
    return [t for t in tokens if t and t not in _STOPWORDS]


@dataclass
class _DocEntry:
    """A document in the BM25 index."""

    name: str
    name_tokens: list[str]
    param_tokens: list[str]
    all_tokens: list[str]
    tf: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for tok in self.all_tokens:
            self.tf[tok] = self.tf.get(tok, 0) + 1


class _BM25Index:
    """Lightweight BM25 index over tool names and descriptions.

    No external dependencies — pure Python using standard BM25 scoring
    (k1=1.5, b=0.75) with IDF weighting, name/param boosting, and prefix
    matching.
    """

    def __init__(self) -> None:
        self._docs: list[_DocEntry] = []
        self._df: dict[str, int] = {}  # document frequency per token
        self._avgdl: float = 0.0
        self._k1: float = 1.5
        self._b: float = 0.75

    def add(self, name: str, description: str, param_names: list[str]) -> None:
        """Add a tool to the index."""
        name_tokens = _tokenize(name)
        desc_tokens = _tokenize(description)
        param_tokens: list[str] = []
        for p in param_names:
            param_tokens.extend(_tokenize(p))
        all_tokens = name_tokens + desc_tokens + param_tokens
        entry = _DocEntry(
            name=name,
            name_tokens=name_tokens,
            param_tokens=param_tokens,
            all_tokens=all_tokens,
        )
        self._docs.append(entry)

    def build(self) -> None:
        """Finalise the index — compute DF and average document length."""
        self._df.clear()
        total_len = 0
        for doc in self._docs:
            total_len += len(doc.all_tokens)
            seen: set[str] = set()
            for tok in doc.all_tokens:
                if tok not in seen:
                    self._df[tok] = self._df.get(tok, 0) + 1
                    seen.add(tok)
        n = len(self._docs)
        self._avgdl = total_len / n if n else 1.0

    def search(
        self,
        query: str,
        max_results: int = 5,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Return ``(tool_name, score)`` pairs sorted by descending score."""
        if not self._docs:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        n = len(self._docs)
        scores: list[tuple[str, float]] = []

        for doc in self._docs:
            score = 0.0
            dl = len(doc.all_tokens)
            name_set = set(doc.name_tokens)
            param_set = set(doc.param_tokens)

            for qt in query_tokens:
                # Exact matches
                tf = doc.tf.get(qt, 0)
                if tf > 0:
                    df = self._df.get(qt, 0)
                    idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                    denom = tf + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
                    tf_norm = (tf * (self._k1 + 1)) / denom
                    term_score = idf * tf_norm

                    # Boost for name and param matches
                    if qt in name_set:
                        term_score *= 1.5
                    if qt in param_set:
                        term_score *= 1.2

                    score += term_score
                else:
                    # Prefix matching at 0.5x weight for fuzzy search
                    for doc_tok in doc.tf:
                        if doc_tok.startswith(qt) or qt.startswith(doc_tok):
                            df = self._df.get(doc_tok, 0)
                            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                            partial_tf = doc.tf[doc_tok]
                            tf_norm = (partial_tf * (self._k1 + 1)) / (
                                partial_tf + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
                            )
                            term_score = idf * tf_norm * 0.5

                            if doc_tok in name_set:
                                term_score *= 1.5
                            if doc_tok in param_set:
                                term_score *= 1.2

                            score += term_score
                            break  # best prefix match per query token

            if score > threshold:
                scores.append((doc.name, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:max_results]


# ---------------------------------------------------------------------------
# Tool search manager
# ---------------------------------------------------------------------------


class ToolSearchManager:
    """Orchestrates BM25 search and tool filtering via ``prepare_tools``.

    Thread-safe: ``_discovered`` is protected by a lock for daemon-mode
    concurrency.  The catalog uses double-checked locking for one-time init.
    """

    def __init__(
        self,
        always_available: list[str],
        max_results: int = 5,
        threshold: float = 0.0,
    ) -> None:
        self._always_available = set(always_available)
        self._max_results = max_results
        self._threshold = threshold

        self._lock = threading.Lock()
        self._discovered: set[str] = set()

        self._catalog_lock = threading.Lock()
        self._catalog: _BM25Index | None = None
        self._catalog_names: set[str] | None = None

    # -- catalog management --------------------------------------------------

    def _ensure_catalog(self, tool_defs: list[ToolDefinition]) -> None:
        """Lazily build BM25 index from tool definitions (double-checked lock)."""
        if self._catalog is not None:
            return
        with self._catalog_lock:
            if self._catalog is not None:
                return  # pragma: no cover - race window
            index = _BM25Index()
            names: set[str] = set()
            for td in tool_defs:
                # Skip the search_tools meta-tool itself
                if td.name == "search_tools":
                    continue
                params = list(td.parameters_json_schema.get("properties", {}).keys())
                index.add(td.name, td.description or "", params)
                names.add(td.name)
            index.build()
            self._catalog = index
            self._catalog_names = names

    # -- search --------------------------------------------------------------

    def search(self, query: str, max_results: int | None = None) -> str:
        """Run BM25 search, add matches to discovered set, return formatted results."""
        if self._catalog is None:
            return "Tool catalog not yet initialised."

        limit = max_results if max_results is not None else self._max_results
        results = self._catalog.search(query, max_results=limit, threshold=self._threshold)

        if not results:
            return f"No tools found matching '{query}'."

        with self._lock:
            for name, _ in results:
                self._discovered.add(name)

        lines = [f"Found {len(results)} tool(s) matching '{query}':"]
        for name, score in results:
            lines.append(f"  - {name} (relevance: {score:.2f})")
        lines.append("\nThese tools are now available for you to call.")
        return "\n".join(lines)

    # -- prepare_tools callback ----------------------------------------------

    async def prepare_tools_callback(
        self,
        ctx: RunContext,
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """PydanticAI ``prepare_tools`` callback — filter visible tools."""
        self._ensure_catalog(tool_defs)
        assert self._catalog_names is not None

        with self._lock:
            discovered = set(self._discovered)

        visible: list[ToolDefinition] = []
        for td in tool_defs:
            if td.name == "search_tools":
                # Always show the meta-tool
                visible.append(td)
            elif td.name in self._always_available:
                visible.append(td)
            elif td.name in discovered:
                visible.append(td)
            elif td.name not in self._catalog_names:
                # Runtime-added tools (e.g. reflection, scheduling) not in
                # the original catalog — always pass through
                visible.append(td)

        return visible

    # -- utility -------------------------------------------------------------

    def reset_discovered(self) -> None:
        """Clear the discovered set (useful for testing or session resets)."""
        with self._lock:
            self._discovered.clear()


# ---------------------------------------------------------------------------
# Toolset factory
# ---------------------------------------------------------------------------


def build_tool_search_toolset(manager: ToolSearchManager) -> FunctionToolset:
    """Build a ``FunctionToolset`` containing the ``search_tools`` meta-tool."""
    toolset = FunctionToolset()

    @toolset.tool
    def search_tools(query: str, max_results: int = 0) -> str:
        """Search for available tools by keyword.

        Use this when you need a tool but don't see it in your current tool
        list.  Describe what you need (e.g. "send slack message", "read csv
        file") and matching tools will be made available for you to call.

        Args:
            query: Natural language description of the tool you need.
            max_results: Maximum number of results (0 = use default).
        """
        limit = max_results if max_results > 0 else None
        return manager.search(query, max_results=limit)

    return toolset
