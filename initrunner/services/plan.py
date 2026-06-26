"""Static, offline dry-run analysis for ``initrunner plan``.

Composes read-only sub-analyses of a role into an :class:`AgentPlan`: reachable
tools (function-level via builder introspection), would-fire initguard policy
decisions, applied guardrails, the sandbox that would engage, armed triggers,
and a heuristic cost estimate. It never calls the model.

Function-level introspection builds individual tool toolsets with a NullBackend
and no audit logger and reads their function names; any builder that fails or
opens a connection is caught and the tool is reported at type level with a
caveat, so the command never blocks. ``introspect=False`` skips construction
entirely (type-level for everything).
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from initrunner.services.cost import RoleCostEstimate, estimate_role_cost_sync

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.tools._registry import ToolBuildContext

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class PolicyDecisionDTO:
    allowed: bool
    reason: str
    advice: str | None = None


@dataclass
class PlannedTool:
    name: str  # concrete function name (or tool type at type-level fallback)
    tool_type: str
    source: str  # spec | skill:<name> | auto:<kind> | tool_search:always
    summary: str = ""
    run_scoped: bool = False
    policy: PolicyDecisionDTO | None = None


@dataclass
class PolicyStatus:
    active: bool
    policy_dir: str | None = None
    policy_count: int | None = None
    rule_count: int | None = None
    agent_checks: bool = False
    note: str | None = None


@dataclass
class GuardrailItem:
    label: str
    value: str


@dataclass
class SandboxDecision:
    requested_backend: str
    resolved_backend: str | None
    available: bool
    status: str
    reason: str | None = None
    network: str = "none"
    mounts_count: int = 0
    memory_limit: str | None = None


@dataclass
class ArmedTrigger:
    type: str
    summary: str
    autonomous: bool
    predictability: str  # scheduled | event
    detail: str


@dataclass
class AgentPlan:
    role_name: str
    role_path: str
    model_label: str
    tools: list[PlannedTool]
    policy: PolicyStatus
    guardrails: list[GuardrailItem]
    sandbox: SandboxDecision
    triggers: list[ArmedTrigger]
    cost: RoleCostEstimate
    tool_search_surfaced: list[str] | None = None
    caveats: list[str] = field(default_factory=list)


@dataclass
class _Fn:
    """Introspected tool function: enough to render and to feed BM25."""

    name: str
    description: str
    params: list[str]


# ---------------------------------------------------------------------------
# Tool enumeration (function-level, side-effect-guarded)
# ---------------------------------------------------------------------------

_SIGNATURE_SKIP = {"self", "ctx", "args", "kwargs", "_orig", "tool_config"}


def _dummy_ctx(role: RoleDefinition, role_dir: Path | None) -> ToolBuildContext:
    """A build context with a NullBackend, so introspection never preflights a
    real sandbox or writes audit."""
    from initrunner.agent.runtime_sandbox.null import NullBackend
    from initrunner.agent.tools._registry import ToolBuildContext

    return ToolBuildContext(role=role, role_dir=role_dir, sandbox_backend=NullBackend())


def _extract_fns(toolset: Any) -> list[_Fn]:
    """Read function name/description/params from a built toolset."""
    fns: list[_Fn] = []
    tools = getattr(toolset, "tools", None)
    if not isinstance(tools, dict):
        return fns
    for name, tool in tools.items():
        fn = getattr(tool, "function", None)
        description = getattr(tool, "description", "") or ""
        if not description and fn is not None:
            doc = inspect.getdoc(fn) or ""
            description = doc.split("\n", 1)[0]
        params: list[str] = []
        if fn is not None:
            try:
                params = [p for p in inspect.signature(fn).parameters if p not in _SIGNATURE_SKIP]
            except (TypeError, ValueError):
                params = []
        fns.append(_Fn(name=str(name), description=description, params=params))
    return fns


def _safe_summary(cfg: Any) -> str:
    try:
        return cfg.summary()
    except Exception:
        return getattr(cfg, "type", "")


def _enumerate_reachable_tools(
    role: RoleDefinition,
    role_dir: Path | None,
    *,
    introspect: bool,
    extra_skill_dirs: list[Path] | None,
) -> tuple[list[PlannedTool], list[_Fn], list[str]]:
    from initrunner.agent.tools._registry import get_builder, is_run_scoped

    tools: list[PlannedTool] = []
    fn_defs: list[_Fn] = []
    caveats: list[str] = []
    ctx = _dummy_ctx(role, role_dir) if introspect else None

    # (config, source) for explicit + skill-contributed tools.
    entries: list[tuple[Any, str]] = [(t, "spec") for t in role.spec.tools]
    if role.spec.skills:
        try:
            from initrunner.agent.skills import resolve_skills

            for rs in resolve_skills(role.spec.skills, role_dir, extra_skill_dirs):
                for t in rs.definition.frontmatter.tools:
                    entries.append((t, f"skill:{rs.definition.frontmatter.name}"))
        except Exception as exc:
            caveats.append(f"Could not resolve skills: {exc}")

    for cfg, source in entries:
        ttype = getattr(cfg, "type", "?")
        summary = _safe_summary(cfg)
        if is_run_scoped(ttype):
            tools.append(
                PlannedTool(ttype, ttype, source, f"{summary} (built per run)", run_scoped=True)
            )
            continue
        builder = get_builder(ttype) if introspect else None
        if builder is None:
            tools.append(PlannedTool(ttype, ttype, source, summary))
            continue
        try:
            fns = _extract_fns(builder(cfg, ctx))
        except Exception as exc:
            tools.append(PlannedTool(ttype, ttype, source, summary))
            caveats.append(f"Could not introspect tool '{ttype}' ({source}); shown at type level.")
            _logger.debug("introspect failed for %s: %s", ttype, exc)
            continue
        if not fns:
            tools.append(PlannedTool(ttype, ttype, source, summary))
            continue
        for fn in fns:
            fn_defs.append(fn)
            tools.append(PlannedTool(fn.name, ttype, source, fn.description or summary))

    auto_tools, auto_fns, auto_caveats = _auto_tool_plans(role, role_dir, introspect)
    tools.extend(auto_tools)
    fn_defs.extend(auto_fns)
    caveats.extend(auto_caveats)
    return tools, fn_defs, caveats


def _auto_tool_plans(
    role: RoleDefinition, role_dir: Path | None, introspect: bool
) -> tuple[list[PlannedTool], list[_Fn], list[str]]:
    """Enumerate auto-wired tools. Mirrors the conditions in
    ``agent/tools/registry.py::build_toolsets`` (retrieval/memory) and the
    tool_search/auto_skills wiring in ``build_agent``."""
    tools: list[PlannedTool] = []
    fns: list[_Fn] = []
    caveats: list[str] = []

    def _try_introspect(build, source: str, fallback_name: str, fallback_desc: str) -> None:
        if introspect:
            try:
                for fn in _extract_fns(build()):
                    fns.append(fn)
                    tools.append(PlannedTool(fn.name, fallback_name, source, fn.description))
                if any(t.source == source for t in tools):
                    return
            except Exception as exc:
                caveats.append(f"Could not introspect {source} tools; shown at type level.")
                _logger.debug("auto-tool introspect failed for %s: %s", source, exc)
        tools.append(PlannedTool(fallback_name, fallback_name, source, fallback_desc))

    if role.spec.ingest is not None:
        from initrunner.agent.tools.retrieval import build_retrieval_toolset
        from initrunner.stores.base import make_store_config

        _try_introspect(
            lambda: build_retrieval_toolset(
                make_store_config(role), sandbox=role.spec.security.tools
            ),
            "auto:retrieval",
            "retrieval",
            "RAG retrieval (ingest configured)",
        )

    memory_cfg = role.spec.memory
    if memory_cfg is not None:
        from initrunner.agent.tools.memory import build_memory_toolset

        provider = getattr(role.spec.model, "provider", "") if role.spec.model else ""
        _try_introspect(
            lambda: build_memory_toolset(
                memory_cfg, role.metadata.name, provider, sandbox=role.spec.security.tools
            ),
            "auto:memory",
            "memory_store",
            "long-term memory (memory configured)",
        )

    ts_cfg = getattr(role.spec, "tool_search", None)
    if ts_cfg is not None and getattr(ts_cfg, "enabled", False):
        tools.append(
            PlannedTool("search_tools", "tool_search", "auto:tool_search", "search available tools")
        )
        for name in getattr(ts_cfg, "always_available", None) or []:
            tools.append(
                PlannedTool(str(name), "tool_search", "tool_search:always", "always shown")
            )

    as_cfg = getattr(role.spec, "auto_skills", None)
    if as_cfg is not None and getattr(as_cfg, "enabled", False):
        tools.append(
            PlannedTool("activate_skill", "auto_skills", "auto:auto_skills", "activate a skill")
        )

    return tools, fns, caveats


# ---------------------------------------------------------------------------
# Policy, guardrails, sandbox, triggers, tool_search surfacing
# ---------------------------------------------------------------------------


def _evaluate_policies(role: RoleDefinition, tools: list[PlannedTool]) -> PolicyStatus:
    try:
        from initrunner.authz import (  # type: ignore[import-not-found]
            EXECUTE,
            TOOL,
            agent_principal_from_role,
            load_authz_config,
            load_engine,
        )
    except ImportError:
        return PolicyStatus(active=False, note="initguard not installed; policy not evaluated")

    config = load_authz_config()
    if config is None:
        return PolicyStatus(
            active=False,
            note="No policy engine active (INITRUNNER_POLICY_DIR unset); all tools allowed",
        )
    try:
        engine = load_engine(config)
    except Exception as exc:
        return PolicyStatus(
            active=False, policy_dir=config.policy_dir, note=f"Policy load failed: {exc}"
        )

    principal = agent_principal_from_role(role.metadata)
    policy_count = rule_count = None
    try:
        raw = engine.info()
        if isinstance(raw, dict):
            policy_count, rule_count = raw.get("policy_count"), raw.get("rule_count")
        else:
            policy_count = getattr(raw, "policy_count", None)
            rule_count = getattr(raw, "rule_count", None)
    except Exception:
        pass

    for tool in tools:
        try:
            decision = engine.check(
                principal,
                TOOL,
                EXECUTE,
                resource_id=tool.name,
                resource_attrs={
                    "tool_type": tool.tool_type,
                    "agent": role.metadata.name,
                    "callable": tool.name,
                },
            )
            tool.policy = PolicyDecisionDTO(
                allowed=bool(decision.allowed),
                reason=getattr(decision, "reason", "") or "",
                advice=getattr(decision, "advice", None),
            )
        except Exception as exc:
            _logger.debug("policy check failed for %s: %s", tool.name, exc)

    return PolicyStatus(
        active=True,
        policy_dir=config.policy_dir,
        policy_count=policy_count,
        rule_count=rule_count,
        agent_checks=config.agent_checks,
    )


def _collect_guardrails(g: Any) -> list[GuardrailItem]:
    items = [
        GuardrailItem("max_tokens_per_run", str(g.max_tokens_per_run)),
        GuardrailItem("max_tool_calls", str(g.max_tool_calls)),
        GuardrailItem("timeout_seconds", f"{g.timeout_seconds}s"),
        GuardrailItem("max_iterations", str(g.max_iterations)),
    ]
    optionals = [
        ("max_request_limit", g.max_request_limit),
        ("input_tokens_limit", g.input_tokens_limit),
        ("total_tokens_limit", g.total_tokens_limit),
        ("session_token_budget", g.session_token_budget),
        ("run_token_budget", g.run_token_budget),
        ("daemon_token_budget", g.daemon_token_budget),
        ("daemon_daily_token_budget", g.daemon_daily_token_budget),
        ("daemon_daily_cost_budget", g.daemon_daily_cost_budget),
        ("daemon_weekly_cost_budget", g.daemon_weekly_cost_budget),
        ("autonomous_token_budget", g.autonomous_token_budget),
        ("autonomous_timeout_seconds", g.autonomous_timeout_seconds),
    ]
    items.extend(GuardrailItem(label, str(val)) for label, val in optionals if val is not None)
    return items


def _probe_sandbox(role: RoleDefinition, role_dir: Path | None, *, probe: bool) -> SandboxDecision:
    cfg = role.spec.security.sandbox
    requested = cfg.backend
    network = getattr(cfg, "network", "none")
    mounts = len(getattr(cfg, "bind_mounts", None) or [])
    mem = getattr(cfg, "memory_limit", None)

    if requested == "none":
        return SandboxDecision(
            requested, "none", True, "none (no isolation)", None, network, mounts, mem
        )
    if not probe:
        return SandboxDecision(
            requested, None, False, "probe skipped (--no-sandbox-probe)", None, network, mounts, mem
        )

    from initrunner.agent.runtime_sandbox import SandboxUnavailableError, resolve_backend
    from initrunner.audit.null import NullAuditLogger

    try:
        backend = resolve_backend(
            cfg, role_dir=role_dir, audit=NullAuditLogger(), agent_name=role.metadata.name
        )
    except SandboxUnavailableError as exc:
        return SandboxDecision(
            requested, None, False, "unavailable", str(exc), network, mounts, mem
        )
    except Exception as exc:
        return SandboxDecision(
            requested, None, False, "probe error", str(exc), network, mounts, mem
        )

    resolved = getattr(backend, "name", requested)
    try:
        backend.preflight()
    except SandboxUnavailableError as exc:
        return SandboxDecision(
            requested, resolved, False, "unavailable", str(exc), network, mounts, mem
        )
    except Exception as exc:
        return SandboxDecision(
            requested, resolved, False, "probe error", str(exc), network, mounts, mem
        )
    return SandboxDecision(requested, resolved, True, "available", None, network, mounts, mem)


def _arm_triggers(role: RoleDefinition) -> list[ArmedTrigger]:
    out: list[ArmedTrigger] = []
    for tr in role.spec.triggers or []:
        ttype = getattr(tr, "type", "?")
        scheduled = ttype in ("cron", "heartbeat")
        out.append(
            ArmedTrigger(
                type=ttype,
                summary=_safe_summary(tr),
                autonomous=bool(getattr(tr, "autonomous", False)),
                predictability="scheduled" if scheduled else "event",
                detail=(
                    "fires on schedule"
                    if scheduled
                    else "armed; fires on an external event, not predictable"
                ),
            )
        )
    return out


def _tool_search_surface(prompt: str, fn_defs: list[_Fn]) -> list[str]:
    from initrunner.agent.tools.tool_search import _BM25Index

    index = _BM25Index()
    for fn in fn_defs:
        index.add(fn.name, fn.description, fn.params)
    index.build()  # compute DF + average doc length before scoring
    return [name for name, _score in index.search(prompt, max_results=10)]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def plan_role(
    role: RoleDefinition,
    role_dir: Path | None,
    *,
    role_path: Path,
    prompt: str | None = None,
    probe_sandbox: bool = True,
    introspect: bool = True,
    extra_skill_dirs: list[Path] | None = None,
) -> AgentPlan:
    """Compose the static dry-run analyses into an :class:`AgentPlan`."""
    caveats = [
        "No model was called; this is a static prediction.",
        "Reachable tools are what the model MAY call; it decides at runtime.",
    ]
    tools, fn_defs, tool_caveats = _enumerate_reachable_tools(
        role, role_dir, introspect=introspect, extra_skill_dirs=extra_skill_dirs
    )
    caveats.extend(tool_caveats)

    policy = _evaluate_policies(role, tools)
    guardrails = _collect_guardrails(role.spec.guardrails)
    sandbox = _probe_sandbox(role, role_dir, probe=probe_sandbox)
    triggers = _arm_triggers(role)

    prompt_tokens = (len(prompt) // 4) if prompt else None
    cost = estimate_role_cost_sync(role_path, prompt_tokens=prompt_tokens)

    surfaced: list[str] | None = None
    ts_cfg = getattr(role.spec, "tool_search", None)
    if prompt and ts_cfg is not None and getattr(ts_cfg, "enabled", False):
        surfaced = _tool_search_surface(prompt, fn_defs)
        caveats.append(
            "tool_search is on: the agent sees always_available tools plus the prompt-surfaced "
            "subset shown here, not every listed tool. Surfacing is deterministic ranking, not a "
            "guarantee the tool is called."
        )

    if any(tr.predictability == "event" for tr in triggers):
        caveats.append("Event triggers are armed but their firing is not predictable.")
    if not introspect:
        caveats.append("Introspection skipped (--no-introspect); tools shown at type level.")
    caveats.append("Cost is a heuristic estimate (excludes skill content; tools counted coarsely).")

    model = role.spec.model
    model_label = (
        f"{model.provider}:{model.name}"
        if model is not None and getattr(model, "name", None)
        else "(auto-detect at runtime)"
    )

    return AgentPlan(
        role_name=role.metadata.name,
        role_path=str(role_path),
        model_label=model_label,
        tools=tools,
        policy=policy,
        guardrails=guardrails,
        sandbox=sandbox,
        triggers=triggers,
        cost=cost,
        tool_search_surfaced=surfaced,
        caveats=caveats,
    )


def plan_role_from_path(
    role_path: Path,
    *,
    prompt: str | None = None,
    probe_sandbox: bool = True,
    introspect: bool = True,
    extra_skill_dirs: list[Path] | None = None,
) -> AgentPlan:
    """Load a role from disk and produce its :class:`AgentPlan`."""
    from initrunner.agent.loader import load_role

    role = load_role(role_path)
    return plan_role(
        role,
        role_path.parent,
        role_path=role_path,
        prompt=prompt,
        probe_sandbox=probe_sandbox,
        introspect=introspect,
        extra_skill_dirs=extra_skill_dirs,
    )
