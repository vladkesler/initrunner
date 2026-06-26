"""CLI ``new`` command -- single entry point for agent creation."""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.syntax import Syntax

from initrunner.cli._helpers import console

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.services.agent_builder import BuilderSession, TurnResult


@dataclass
class PreflightResult:
    """Outcome of a credential preflight, carrying the resolved (possibly
    switched) provider/model/preset so the caller seeds with the right values.
    """

    outcome: str  # "ok" | "form" | "abort"
    provider: str
    model: str | None
    base_url: str | None
    api_key_env: str | None


@dataclass
class _WizardCtx:
    """Resolved context returned by the guided/offline entry path."""

    provider: str
    model: str | None
    base_url: str | None
    api_key_env: str | None
    ai_available: bool


@dataclass
class _LoopCtx:
    """State the refinement-loop commands operate on."""

    session: BuilderSession
    provider: str
    model: str | None
    base_url: str | None
    api_key_env: str | None


def _stdin_is_interactive() -> bool:
    """Indirection over ``sys.stdin.isatty()`` so tests can monkeypatch it."""
    return sys.stdin.isatty()


def _ask(prompt: str, **kwargs: object) -> str:
    """``Prompt.ask`` that turns Ctrl-C/EOF into a clean exit."""
    from rich.prompt import Prompt

    try:
        return Prompt.ask(prompt, **kwargs)  # type: ignore[arg-type]
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit() from None


def _confirm(prompt: str, *, default: bool = False) -> bool:
    """``typer.confirm`` that turns Ctrl-C/EOF into a clean exit."""
    try:
        return typer.confirm(prompt, default=default)
    except (KeyboardInterrupt, EOFError, typer.Abort):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit() from None


def _key_available(provider: str, api_key_env: str | None) -> bool:
    """True if the active provider can make an AI call (keyless or key set)."""
    if provider in ("ollama", "bedrock"):
        return True
    from initrunner.credentials import get_resolver
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT

    env_var = api_key_env or PROVIDER_KEY_ENVS_DICT.get(provider)
    if not env_var:
        return False
    return bool(get_resolver().get(env_var))


def _handle_builder_error(exc: Exception, provider: str, *, fatal: bool = True) -> bool:
    """Handle LLM errors from the builder agent.

    Returns ``True`` if the error was recognized and a message was printed,
    ``False`` otherwise (caller should fall back to generic handling).
    """
    from pydantic_ai.exceptions import ModelHTTPError

    if isinstance(exc, ModelHTTPError):
        if exc.status_code == 401:
            console.print(
                f"[red]Authentication failed[/red] for provider [bold]{provider}[/bold].\n"
                "Your API key is missing or invalid.\n\n"
                "Fix: run [bold]initrunner setup[/bold] or pass [bold]--provider <name>[/bold]."
            )
        else:
            console.print(f"[red]Model API error ({exc.status_code}):[/red] {exc}")
        return True
    return False


def _dispatch_run(yaml_path: Path, prompt: str) -> None:
    """Run the freshly-created agent via the canonical ``initrunner run`` path."""
    from initrunner.cli._run_agent import _run_agent

    _run_agent(
        role_file=yaml_path,
        prompt=prompt,
        interactive=False,
        autonomous=False,
        max_iterations=None,
        token_budget=None,
        resume=False,
        dry_run=False,
        audit_db=None,
        no_audit=False,
        skill_dir=None,
        attach=None,
        report=None,
        report_template="default",
        output_format="auto",
        no_stream=False,
        model=None,
    )


def _offer_post_create_run(
    *,
    yaml_path: Path,
    role: RoleDefinition | None,
    valid: bool,
    test_prompt: str | None,
    run_prompt: str | None,
    no_run: bool,
) -> None:
    """After ``new`` writes the YAML, optionally execute the agent in one shot.

    Gating order (each branch is a hard return):

    1. ``--run TEXT`` -- explicit scripting path. Dispatches with that prompt
       regardless of TTY, validity, or role kind. The loader surfaces any
       errors the same way ``initrunner run`` would.
    2. ``--no-run`` -- explicit opt-out.
    3. The save was invalid -- don't implicitly run broken YAML.
    4. The role isn't a runnable one-shot (has triggers, or needs ingestion).
       Daemon agents have a separate ``--daemon`` path; ingest-required
       agents need ``initrunner ingest`` first. Both are already covered by
       the printed "Next steps" guidance.
    5. The builder didn't produce a tailored test prompt (e.g. blank seed
       without refinement). We promised tailored, so we don't fall back to
       a generic prompt -- explicit ``--run`` still works.
    6. Stdin isn't interactive -- don't surprise pipes/CI.
    7. Confirm with the user, then dispatch.
    """
    if run_prompt is not None:
        _dispatch_run(yaml_path, run_prompt)
        return
    if no_run:
        return
    if not valid:
        return
    if role is None:
        return
    if role.spec.triggers:
        return
    if role.spec.ingest:
        return
    if test_prompt is None:
        return
    if not _stdin_is_interactive():
        return
    if not typer.confirm(f"\nRun it now with prompt: {test_prompt!r}?", default=True):
        return
    _dispatch_run(yaml_path, test_prompt)


def new(
    description: Annotated[str | None, typer.Argument(help="Agent description")] = None,
    from_source: Annotated[
        str | None, typer.Option("--from", help="Source: file path, example name, or hub:ref")
    ] = None,
    template: Annotated[str | None, typer.Option("--template", help="Template name")] = None,
    blank: Annotated[bool, typer.Option("--blank", help="Start from blank template")] = False,
    langchain: Annotated[
        str | None, typer.Option("--langchain", help="Import from LangChain Python file")
    ] = None,
    pydantic_ai: Annotated[
        str | None, typer.Option("--pydantic-ai", help="Import from PydanticAI Python file")
    ] = None,
    agent_spec: Annotated[
        str | None,
        typer.Option("--agent-spec", help="Import from PydanticAI Agent Spec YAML/JSON file"),
    ] = None,
    list_templates: Annotated[
        bool, typer.Option("--list-templates", help="Show available templates and exit")
    ] = False,
    provider: Annotated[str | None, typer.Option(help="Model provider")] = None,
    model: Annotated[str | None, typer.Option(help="Model name")] = None,
    output: Annotated[Path, typer.Option(help="Output file path")] = Path("role.yaml"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing file")] = False,
    no_refine: Annotated[bool, typer.Option("--no-refine", help="Skip refinement loop")] = False,
    run: Annotated[
        str | None,
        typer.Option("--run", metavar="PROMPT", help="Execute the new agent with this prompt"),
    ] = None,
    no_run: Annotated[
        bool,
        typer.Option("--no-run", help="Skip the post-creation 'Run it now?' prompt"),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Build via a structured form, no AI/LLM call"),
    ] = False,
) -> None:
    """Create a new agent role via conversational builder.

    Seed modes (mutually exclusive):
      DESCRIPTION          Generate from natural language
      --from SOURCE        Local file, example name, or hub:ref
      --template NAME      Start from a named template
      --blank              Start from minimal blank template

    Without any seed, starts an interactive conversation.
    """
    # --- List templates (pure informational, exit early) ---
    if list_templates:
        from rich.table import Table

        from initrunner.templates import LISTABLE_TEMPLATES

        table = Table(title="Available Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        for name, desc in sorted(LISTABLE_TEMPLATES.items()):
            table.add_row(name, desc)
        console.print(table)
        console.print("\n[dim]Usage: initrunner new --template <name>[/dim]")
        raise typer.Exit(0)

    from pydantic_ai.exceptions import ModelHTTPError

    from initrunner.agent.loader import _load_dotenv, detect_default_model
    from initrunner.services.agent_builder import BuilderSession

    _load_dotenv(Path.cwd())

    # --- Mutual exclusivity check ---
    seed_count = sum(
        [
            description is not None,
            from_source is not None,
            template is not None,
            blank,
            langchain is not None,
            pydantic_ai is not None,
            agent_spec is not None,
            offline,
        ]
    )
    if seed_count > 1:
        console.print(
            "[red]Error:[/red] Specify at most one of: DESCRIPTION, --from, --template,"
            " --blank, --langchain, --pydantic-ai, --agent-spec, --offline"
        )
        raise typer.Exit(1)

    if run is not None and no_run:
        console.print("[red]Error:[/red] --run and --no-run are mutually exclusive.")
        raise typer.Exit(1)

    # --- Resolve provider/model defaults ---
    # Precedence: CLI flags > INITRUNNER_MODEL env > run.yaml > env auto-detect
    base_url: str | None = None
    api_key_env: str | None = None
    if provider is None or model is None:
        d_prov, d_model, d_base_url, d_api_key_env, _src = detect_default_model()
        if provider is None:
            provider = d_prov or "openai"
        if model is None and d_model:
            model = d_model
        base_url = d_base_url
        api_key_env = d_api_key_env

    # --- Scaffold shortcuts (non-YAML templates) ---
    if template == "tool":
        _scaffold_tool(output, provider)
        return
    if template == "skill":
        console.print("[dim]Tip: use 'initrunner skill new <name>' instead.[/dim]")
        _scaffold_skill(output)
        return

    session = BuilderSession()

    if offline and not _stdin_is_interactive():
        console.print("[red]Error:[/red] --offline requires an interactive terminal.")
        raise typer.Exit(1)

    # No seed args + interactive => guided start menu. Non-TTY no-seed keeps the
    # canned LLM fallback in _seed_session (pipes/CI behave as before).
    no_seed = seed_count == 0
    use_guided = offline or (no_seed and _stdin_is_interactive())

    # --- Seed ---
    ai_available = True
    try:
        if use_guided:
            turn, ctx = _run_guided_or_offline(
                session,
                offline=offline,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
            )
            provider, model = ctx.provider, ctx.model
            base_url, api_key_env = ctx.base_url, ctx.api_key_env
            ai_available = ctx.ai_available
        else:
            turn = _seed_session(
                session,
                description,
                from_source,
                template,
                blank,
                langchain,
                pydantic_ai,
                agent_spec,
                provider,
                model,
                base_url=base_url,
                api_key_env=api_key_env,
            )
            ai_available = _key_available(provider, api_key_env)
    except (ValueError, FileNotFoundError, OSError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except ModelHTTPError as e:
        _handle_builder_error(e, provider)
        raise typer.Exit(1) from None

    # Inject base_url/api_key_env into generated YAML
    if base_url:
        from initrunner.services.agent_builder import rewrite_model_block

        session.yaml_text = rewrite_model_block(
            session.yaml_text, base_url=base_url, api_key_env=api_key_env
        )

    # --- Show initial result ---
    _display_turn(turn, session)

    # --- Show import warnings ---
    if turn.import_warnings:
        console.print("\n[bold yellow]Import warnings:[/bold yellow]")
        for w in turn.import_warnings:
            console.print(f"  [yellow]-[/yellow] {w}")

    # --- Show omitted asset warnings ---
    if session.omitted_assets:
        assets = ", ".join(session.omitted_assets)
        console.print(f"[yellow]Warning:[/yellow] Omitted sidecar files: {assets}")

    # --- Refinement loop ---
    if not no_refine:
        turn = _refinement_loop(
            session,
            turn,
            provider,
            model,
            base_url=base_url,
            api_key_env=api_key_env,
            ai_available=ai_available,
        )
        if turn is None:
            # User quit
            console.print("[dim]Discarded.[/dim]")
            raise typer.Exit()

    # --- Save ---
    if output.exists() and not force:
        if not typer.confirm(f"{output} already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        force = True  # User confirmed

    try:
        result = session.save(output, force=force)
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # --- Post-creation output ---
    console.print(f"\n[green]Created[/green] {result.yaml_path}")

    if not result.valid:
        if session.issues:
            from initrunner.cli._validation_panel import render_validation_panel

            console.print(render_validation_panel(result.yaml_path, "agent", session.issues))
        else:
            # Raw save-exception text has no structured form.
            for issue in result.issues:
                console.print(f"[yellow]Warning:[/yellow] {issue}")

    if result.generated_assets:
        console.print("\n[bold]Generated files:[/bold]")
        for asset_path in result.generated_assets:
            console.print(f"  [green]+[/green] {asset_path}")

    if result.omitted_assets:
        console.print(
            f"[dim]Note: omitted files from bundle: {', '.join(result.omitted_assets)}[/dim]"
        )

    console.print("\n[bold]Next steps:[/bold]")
    for step in result.next_steps:
        console.print(f"  {step}")

    _offer_post_create_run(
        yaml_path=result.yaml_path,
        role=session.role,
        valid=result.valid,
        test_prompt=turn.test_prompt,
        run_prompt=run,
        no_run=no_run,
    )


def _seed_session(
    session: BuilderSession,
    description: str | None,
    from_source: str | None,
    template: str | None,
    blank: bool,
    langchain: str | None,
    pydantic_ai: str | None,
    agent_spec: str | None,
    provider: str,
    model: str | None,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> TurnResult:
    """Resolve seed mode and execute it. Returns the initial TurnResult."""

    if blank:
        return session.seed_blank(provider, model)

    if template is not None:
        return session.seed_template(template, provider, model)

    if from_source is not None:
        return _seed_from_source(session, from_source, provider, model)

    if agent_spec is not None:
        spec_path = Path(agent_spec)
        if not spec_path.exists():
            raise FileNotFoundError(f"Agent-spec file not found: {spec_path}")
        return session.seed_from_agent_spec(spec_path)

    # LLM-backed seeds below -- verify SDK is installed for the provider
    from initrunner._compat import require_provider

    require_provider(provider)

    if langchain is not None:
        lc_path = Path(langchain)
        if not lc_path.exists():
            raise FileNotFoundError(f"LangChain file not found: {lc_path}")
        with console.status("Importing LangChain agent..."):
            return session.seed_from_langchain(
                lc_path, provider, model, base_url=base_url, api_key_env=api_key_env
            )

    if pydantic_ai is not None:
        pai_path = Path(pydantic_ai)
        if not pai_path.exists():
            raise FileNotFoundError(f"PydanticAI file not found: {pai_path}")
        with console.status("Importing PydanticAI agent..."):
            return session.seed_from_pydanticai(
                pai_path, provider, model, base_url=base_url, api_key_env=api_key_env
            )

    if description is not None:
        with console.status("Generating..."):
            return session.seed_description(
                description, provider, model, base_url=base_url, api_key_env=api_key_env
            )

    # No seed -- interactive: ask LLM what to build
    with console.status("Generating..."):
        return session.seed_description(
            "Ask the user what kind of agent they want to build. "
            "Start by asking clarifying questions.",
            provider,
            model,
            base_url=base_url,
            api_key_env=api_key_env,
        )


def _seed_from_source(
    session: BuilderSession,
    source: str,
    provider: str,
    model: str | None,
) -> TurnResult:
    """Resolve --from SOURCE: hub ref, local file, or example name."""
    if source.startswith("hub:"):
        ref = source[4:]
        with console.status(f"Fetching from hub: {ref}..."):
            return session.seed_from_hub(ref)

    path = Path(source)
    if path.exists():
        return session.seed_from_file(path)

    # Try as example name
    return session.seed_from_example(source)


# ---------------------------------------------------------------------------
# Guided start menu + offline form + credential preflight
# ---------------------------------------------------------------------------


def _run_guided_or_offline(
    session: BuilderSession,
    *,
    offline: bool,
    provider: str,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
) -> tuple[TurnResult, _WizardCtx]:
    """Drive the guided start menu (or jump straight to the offline form).

    Returns the seeded ``TurnResult`` plus the resolved context (provider/model
    may change via preflight or a manual switch; ``ai_available`` tells the
    refinement loop whether plain-text AI refinement is possible).
    """
    if offline:
        return _offline_form(session, provider, model, base_url, api_key_env)

    key = _start_menu()

    if key == "describe":
        pf = _preflight_then(provider, model, base_url, api_key_env)
        if pf.outcome == "abort":
            raise typer.Exit()
        if pf.outcome == "form":
            return _offline_form(session, pf.provider, pf.model, pf.base_url, pf.api_key_env)
        desc = _ask("Describe your agent")
        with console.status("Generating..."):
            turn = session.seed_description(
                desc, pf.provider, pf.model, base_url=pf.base_url, api_key_env=pf.api_key_env
            )
        return turn, _WizardCtx(pf.provider, pf.model, pf.base_url, pf.api_key_env, True)

    if key == "template":
        name = _pick_template()
        turn = (
            session.seed_blank(provider, model)
            if name == "blank"
            else session.seed_template(name, provider, model)
        )
        return turn, _WizardCtx(
            provider, model, base_url, api_key_env, _key_available(provider, api_key_env)
        )

    if key == "example":
        name = _pick_example()
        turn = session.seed_from_example(name)
        return turn, _WizardCtx(
            provider, model, base_url, api_key_env, _key_available(provider, api_key_env)
        )

    if key == "import":
        return _run_import(session, provider, model, base_url, api_key_env)

    # "offline"
    return _offline_form(session, provider, model, base_url, api_key_env)


def _start_menu() -> str:
    """Show the guided start menu and return the chosen option key."""
    from initrunner.services.wizard import START_OPTIONS

    console.print("\n[bold]How would you like to start?[/bold]\n")
    for i, opt in enumerate(START_OPTIONS, 1):
        marker = "   [dim](default)[/dim]" if i == 1 else ""
        console.print(f"  [bold]{i}[/bold]. {opt.label}   [dim]({opt.annotation})[/dim]{marker}")
    raw = _ask(
        "\nWhat would you like to do?",
        choices=[str(i) for i in range(1, len(START_OPTIONS) + 1)],
        default="1",
    )
    return START_OPTIONS[int(raw) - 1].key


def _pick_template() -> str:
    """Show the template picker and return the chosen template name."""
    from initrunner.services.wizard import list_wizard_templates

    items = list_wizard_templates()
    console.print("\n[bold]Templates:[/bold]")
    for i, (name, desc) in enumerate(items, 1):
        console.print(f"  [bold]{i}[/bold]. {name} — {desc}")
    raw = _ask("Template", choices=[str(i) for i in range(1, len(items) + 1)], default="1")
    return items[int(raw) - 1][0]


def _pick_example() -> str:
    """Show the example picker and return the chosen example name."""
    from rich.table import Table

    from initrunner.services.wizard import list_example_entries

    entries = list_example_entries()
    if not entries:
        console.print("[yellow]No examples available.[/yellow]")
        raise typer.Exit(1)
    table = Table(title="Examples")
    table.add_column("#", style="cyan")
    table.add_column("Name")
    table.add_column("Description")
    for i, e in enumerate(entries, 1):
        table.add_row(str(i), e.name, e.description)
    console.print(table)
    raw = _ask("Example", choices=[str(i) for i in range(1, len(entries) + 1)], default="1")
    return entries[int(raw) - 1].name


def _pick_provider() -> str | None:
    """Show a provider picker. Returns the provider name or None if invalid."""
    from initrunner.services.setup import ALL_PROVIDERS, PROVIDER_DESCRIPTIONS

    console.print("\n[bold]Select a provider:[/bold]")
    for i, p in enumerate(ALL_PROVIDERS, 1):
        console.print(f"  [bold]{i}[/bold]. {p} — {PROVIDER_DESCRIPTIONS.get(p, '')}")
    raw = _ask("Provider", default="1").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(ALL_PROVIDERS):
        return ALL_PROVIDERS[int(raw) - 1]
    if raw in ALL_PROVIDERS:
        return raw
    return None


def _pick_tools() -> list[dict]:
    """Multi-select tools and collect their required/optional config."""
    from initrunner.services import wizard

    choices = wizard.list_tool_choices()
    console.print("\n[bold]Tools[/bold] (comma-separated numbers, or Enter for none):")
    for i, c in enumerate(choices, 1):
        need = f"  [dim](needs: {', '.join(c.required_fields)})[/dim]" if c.required_fields else ""
        console.print(f"  [bold]{i}[/bold]. {c.type} — {c.description}{need}")
    raw = _ask("Select tools", default="").strip()
    if not raw:
        return []

    tools: list[dict] = []
    for part in raw.split(","):
        part = part.strip()
        if not (part.isdigit() and 1 <= int(part) <= len(choices)):
            continue
        c = choices[int(part) - 1]
        tool: dict = {"type": c.type}
        skip = False
        for fname, fprompt, fdefault in c.fields:
            raw_val = _ask(f"  {c.type}.{fname} — {fprompt}", default=fdefault)
            value = wizard.coerce_field_value(raw_val)
            if value is None:
                if fname in c.required_fields:
                    console.print(f"  [yellow]Skipped {c.type}: {fname} is required.[/yellow]")
                    skip = True
                    break
                continue
            tool[fname] = value
        if not skip:
            tools.append(tool)
    return tools


def _run_import(
    session: BuilderSession,
    provider: str,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
) -> tuple[TurnResult, _WizardCtx]:
    """Guided import: pick a source kind + path, then seed (preflight if AI)."""
    console.print("\n[bold]Import:[/bold]")
    console.print("  [bold]1[/bold]. LangChain Python file")
    console.print("  [bold]2[/bold]. PydanticAI Python file")
    console.print("  [bold]3[/bold]. PydanticAI Agent Spec (YAML/JSON)")
    kind = _ask("Source type", choices=["1", "2", "3"], default="1")
    path = Path(_ask("Path to file").strip())
    if not path.exists():
        console.print(f"[red]Error:[/red] File not found: {path}")
        raise typer.Exit(1)

    if kind == "3":  # agent-spec is deterministic, no key needed
        turn = session.seed_from_agent_spec(path)
        return turn, _WizardCtx(
            provider, model, base_url, api_key_env, _key_available(provider, api_key_env)
        )

    pf = _preflight_then(provider, model, base_url, api_key_env)
    if pf.outcome == "abort":
        raise typer.Exit()
    if pf.outcome == "form":
        return _offline_form(session, pf.provider, pf.model, pf.base_url, pf.api_key_env)

    if kind == "1":
        with console.status("Importing LangChain agent..."):
            turn = session.seed_from_langchain(
                path, pf.provider, pf.model, base_url=pf.base_url, api_key_env=pf.api_key_env
            )
    else:
        with console.status("Importing PydanticAI agent..."):
            turn = session.seed_from_pydanticai(
                path, pf.provider, pf.model, base_url=pf.base_url, api_key_env=pf.api_key_env
            )
    return turn, _WizardCtx(pf.provider, pf.model, pf.base_url, pf.api_key_env, True)


def _offline_form(
    session: BuilderSession,
    provider: str,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
) -> tuple[TurnResult, _WizardCtx]:
    """Deterministic, no-LLM structured form. Returns the seeded turn + context."""
    from initrunner.cli._helpers._display import prompt_model_selection
    from initrunner.services import wizard

    console.print("\n[bold]Build an agent (offline, no AI)[/bold]")

    while True:
        name = _ask("Agent name", default="my-agent").strip()
        if wizard.validate_agent_name(name):
            break
        console.print(
            "[yellow]Name must be lowercase letters, digits, and hyphens (e.g. my-agent).[/yellow]"
        )

    description = _ask("One-line description", default="").strip()
    system_prompt = _ask("System prompt", default="You are a helpful assistant.")
    if _confirm("Open an editor for a longer system prompt?", default=False):
        edited = typer.edit(system_prompt)
        if edited is not None:
            system_prompt = edited.strip()

    if not _confirm(f"Use provider '{provider}'?", default=True):
        picked = _pick_provider()
        if picked is not None:
            provider, base_url, api_key_env = picked, None, None

    ollama_models = None
    if provider == "ollama":
        from initrunner.services.providers import list_ollama_models

        ollama_models = list_ollama_models()
    model = prompt_model_selection(provider, ollama_models=ollama_models)

    tools = _pick_tools()
    memory = _confirm("Enable long-term memory?", default=False)

    ingest_sources = None
    if _confirm("Answer from your documents (RAG)?", default=False):
        raw = _ask("Document source glob(s), comma-separated", default="./docs")
        ingest_sources = [s.strip() for s in raw.split(",") if s.strip()]

    triggers = None
    if _confirm("Add a schedule trigger (cron)?", default=False):
        schedule = _ask("Cron schedule", default="0 * * * *")
        tprompt = _ask("Prompt to run on schedule", default="Run the scheduled task.")
        triggers = [{"type": "cron", "schedule": schedule, "prompt": tprompt}]

    spec = wizard.OfflineFormSpec(
        name=name,
        description=description,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        tools=tools,
        memory=memory,
        ingest_sources=ingest_sources,
        triggers=triggers,
    )
    turn = session.seed_yaml(wizard.build_offline_yaml(spec), source_label="offline-form")
    return turn, _WizardCtx(
        provider, model, base_url, api_key_env, _key_available(provider, api_key_env)
    )


def _preflight_then(
    provider: str,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
    *,
    _switch_allowed: bool = True,
) -> PreflightResult:
    """Check the provider has a usable API key before an AI seed.

    Resolves a concrete model (so the transparency line never shows
    ``provider:None``), prints ``Using <provider>:<model>``, and on a missing
    key (TTY only) offers: enter a key, switch provider, or build offline.
    Non-TTY preserves the existing late-401 behavior.
    """
    from rich.prompt import Prompt

    from initrunner.templates import _default_model_name

    if not model:
        model = _default_model_name(provider)

    if provider == "ollama":
        from initrunner.services.providers import is_ollama_running

        if not is_ollama_running():
            console.print(
                "[yellow]Ollama does not appear to be running at the default URL.[/yellow]"
            )
        console.print(f"[dim]Using {provider}:{model}[/dim]")
        return PreflightResult("ok", provider, model, base_url, api_key_env)

    if provider == "bedrock":
        console.print(f"[dim]Using {provider}:{model}[/dim]")
        return PreflightResult("ok", provider, model, base_url, api_key_env)

    from initrunner.credentials import get_resolver
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT

    env_var = api_key_env or PROVIDER_KEY_ENVS_DICT.get(provider)
    if env_var and get_resolver().get(env_var):
        console.print(f"[dim]Using {provider}:{model}[/dim]")
        return PreflightResult("ok", provider, model, base_url, api_key_env)

    if not _stdin_is_interactive():
        # Non-TTY: keep today's behavior (the LLM call surfaces a 401 itself).
        return PreflightResult("ok", provider, model, base_url, api_key_env)

    console.print(f"[yellow]No API key configured for {provider}.[/yellow]")
    try:
        choice = Prompt.ask(
            "  (1) enter a key   (2) switch provider   (3) build offline (no AI)",
            choices=["1", "2", "3"],
            default="1",
        )
    except (KeyboardInterrupt, EOFError):
        return PreflightResult("abort", provider, model, base_url, api_key_env)

    if choice == "1":
        from initrunner.cli._helpers._context import prompt_inline_api_key

        if env_var and prompt_inline_api_key(env_var, provider):
            console.print(f"[dim]Using {provider}:{model}[/dim]")
            return PreflightResult("ok", provider, model, base_url, api_key_env)
        return PreflightResult("form", provider, model, base_url, api_key_env)

    if choice == "2" and _switch_allowed:
        picked = _pick_provider()
        if picked is None:
            return PreflightResult("form", provider, model, base_url, api_key_env)
        return _preflight_then(picked, None, None, None, _switch_allowed=False)

    return PreflightResult("form", provider, model, base_url, api_key_env)


def _yaml_panel(yaml_text: str, issues: list, session: BuilderSession) -> Panel:
    """Build the syntax-highlighted YAML panel with a validation status title."""
    name = "new-agent"
    if session.role and session.role.metadata.name:
        name = session.role.metadata.name

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    if error_count:
        status = f"[red]{error_count} error(s)[/red]"
    elif warning_count:
        status = f"[yellow]{warning_count} warning(s)[/yellow]"
    else:
        status = "[green]VALID[/green]"

    syntax = Syntax(yaml_text, "yaml", theme="monokai", line_numbers=False)
    return Panel(syntax, title=f"{name} -- {status}", border_style="cyan")


def _display_turn(turn: TurnResult, session: BuilderSession) -> None:
    """Display a TurnResult with syntax-highlighted YAML panel."""
    if turn.explanation:
        console.print(f"\n{turn.explanation}\n")
    console.print(_yaml_panel(turn.yaml_text, turn.issues, session))


# ---------------------------------------------------------------------------
# Refinement-loop commands (':' prefix)
# ---------------------------------------------------------------------------

_CMD_CONTINUE = "continue"
_CMD_SAVE = "save"
_CMD_QUIT = "quit"


def _print_change_summary(old: str, new: str) -> None:
    """One-line +adds/-removes summary after a refinement."""
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""))
    adds = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    rems = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    if adds or rems:
        console.print(
            f"[dim]Changed: [green]+{adds}[/green] [red]-{rems}[/red] lines"
            " ([bold]:diff[/bold] for details)[/dim]"
        )


def _render_unified_diff(old: str, new: str) -> None:
    """Print a colorized unified diff of two YAML strings."""
    from rich.text import Text

    lines = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile="previous", tofile="current", lineterm=""
        )
    )
    if not lines:
        console.print("[dim]No changes.[/dim]")
        return
    body = Text()
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            body.append(line + "\n", style="green")
        elif line.startswith("-") and not line.startswith("---"):
            body.append(line + "\n", style="red")
        elif line.startswith("@@"):
            body.append(line + "\n", style="cyan")
        else:
            body.append(line + "\n", style="dim")
    console.print(Panel(body, title="diff: previous -> current", border_style="cyan"))


def _pick_model(provider: str) -> tuple[str, str] | None:
    """Numbered model picker from PROVIDER_MODELS. Returns (provider, name) or None."""
    from initrunner.templates import PROVIDER_MODELS

    models = PROVIDER_MODELS.get(provider, [])
    if not models:
        console.print(
            f"[yellow]No model list for '{provider}'.[/yellow] Use :model {provider}:<name>."
        )
        return None
    console.print(f"\n[bold]Models for {provider}:[/bold]")
    for i, (mid, desc) in enumerate(models, 1):
        console.print(f"  [bold]{i}[/bold]. {mid} — {desc}")
    raw = _ask("Model (number, or Enter to cancel)", default="").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(models):
        return provider, models[int(raw) - 1][0]
    return None


def _cmd_help(arg: str, ctx: _LoopCtx) -> str:
    from rich.markup import escape

    console.print("\n[bold]Commands[/bold] (prefix with ':', or '?' for this help)\n")
    for group in ("inspect", "edit", "exit"):
        console.print(f"  [dim]{group}[/dim]")
        for _name, (_handler, grp, usage, desc) in _COMMANDS.items():
            if grp == group:
                # escape() so a usage like ':model [p:name]' isn't read as markup.
                col = escape(f"{usage:<16}")
                console.print(f"    [bold cyan]{col}[/bold cyan] [dim]{desc}[/dim]")
        console.print()
    console.print("  Plain text (no ':') is sent to the AI to refine the agent.\n")
    return _CMD_CONTINUE


def _cmd_yaml(arg: str, ctx: _LoopCtx) -> str:
    console.print(_yaml_panel(ctx.session.yaml_text, ctx.session.issues, ctx.session))
    return _CMD_CONTINUE


def _cmd_validate(arg: str, ctx: _LoopCtx) -> str:
    from initrunner.cli._validation_panel import render_validation_panel

    role = ctx.session.role
    kind = str(role.kind) if role else "agent"
    console.print(render_validation_panel(Path("(draft)"), kind, ctx.session.issues))
    return _CMD_CONTINUE


def _cmd_explain(arg: str, ctx: _LoopCtx) -> str:
    from initrunner.services.roles import explain_role

    role = ctx.session.role
    if role is None:
        console.print(
            "[yellow]Can't explain yet — fix validation errors first (:validate).[/yellow]"
        )
        return _CMD_CONTINUE
    console.print()
    for section, text in explain_role(role):
        console.print(f"[bold]{section}[/bold]: {text}")
    return _CMD_CONTINUE


def _cmd_tools(arg: str, ctx: _LoopCtx) -> str:
    from initrunner.agent.tools._registry import get_tool_types

    console.print(f"\n[bold]Available tool types:[/bold]\n  {', '.join(sorted(get_tool_types()))}")
    role = ctx.session.role
    current = role.spec.tools if role else []
    if current:
        console.print("[bold]Current tools:[/bold]")
        for t in current:
            console.print(f"  - {t.type}")
    else:
        console.print("[dim]No tools configured yet.[/dim]")
    return _CMD_CONTINUE


def _cmd_model(arg: str, ctx: _LoopCtx) -> str:
    from initrunner.services.agent_builder import rewrite_model_block

    if arg:
        prov, sep, name = arg.partition(":")
        if not sep or not name.strip():
            console.print("[yellow]Usage:[/yellow] :model <provider>:<name>  (or bare :model)")
            return _CMD_CONTINUE
        prov, name = prov.strip(), name.strip()
    else:
        picked = _pick_model(ctx.provider)
        if picked is None:
            return _CMD_CONTINUE
        prov, name = picked

    ctx.session.checkpoint()
    ctx.session.yaml_text = rewrite_model_block(
        ctx.session.yaml_text,
        provider=prov,
        name=name,
        base_url=ctx.base_url,
        api_key_env=ctx.api_key_env,
    )
    console.print(f"[green]Model set:[/green] {prov}:{name}")
    return _CMD_CONTINUE


def _cmd_diff(arg: str, ctx: _LoopCtx) -> str:
    prev = ctx.session.previous_yaml
    if prev is None:
        console.print("[dim]No previous version to diff against.[/dim]")
        return _CMD_CONTINUE
    _render_unified_diff(prev, ctx.session.yaml_text)
    return _CMD_CONTINUE


def _cmd_undo(arg: str, ctx: _LoopCtx) -> str:
    if ctx.session.undo():
        console.print("[dim]Reverted.[/dim]")
        console.print(_yaml_panel(ctx.session.yaml_text, ctx.session.issues, ctx.session))
    else:
        console.print("[yellow]Nothing to undo.[/yellow]")
    return _CMD_CONTINUE


def _cmd_save(arg: str, ctx: _LoopCtx) -> str:
    return _CMD_SAVE


def _cmd_quit(arg: str, ctx: _LoopCtx) -> str:
    return _CMD_QUIT


# name -> (handler, group, usage, description); also the source of truth for :help
_COMMANDS: dict[str, tuple] = {
    "help": (_cmd_help, "", ":help", "Show this list"),
    "yaml": (_cmd_yaml, "inspect", ":yaml", "Show the full current YAML"),
    "validate": (_cmd_validate, "inspect", ":validate", "Show the validation panel"),
    "explain": (_cmd_explain, "inspect", ":explain", "Plain-English section summary"),
    "tools": (_cmd_tools, "inspect", ":tools", "Available tool types + current tools"),
    "diff": (_cmd_diff, "inspect", ":diff", "Unified diff vs the previous turn"),
    "model": (_cmd_model, "edit", ":model [p:name]", "Change the model (no AI)"),
    "undo": (_cmd_undo, "edit", ":undo", "Revert the last change"),
    "save": (_cmd_save, "exit", ":save", "Save and exit (also: empty line)"),
    "quit": (_cmd_quit, "exit", ":quit", "Discard and exit (also: q)"),
}


def _handle_command(raw: str, ctx: _LoopCtx) -> str:
    """Dispatch a ':' command (or '?' for help). Returns a _CMD_* signal."""
    if raw.strip() == "?":
        raw = ":help"
    body = raw[1:].strip() if raw.startswith(":") else raw.strip()
    parts = body.split(maxsplit=1)
    name = parts[0].lower() if parts else "help"
    arg = parts[1] if len(parts) > 1 else ""
    entry = _COMMANDS.get(name)
    if entry is None:
        console.print(f"[yellow]Unknown command[/yellow] :{name}. Type [bold]:help[/bold].")
        return _CMD_CONTINUE
    return entry[0](arg, ctx)


def _refinement_loop(
    session: BuilderSession,
    turn: TurnResult,
    provider: str,
    model: str | None,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
    ai_available: bool = True,
) -> TurnResult | None:
    """Interactive refinement loop. Returns final TurnResult or None if user quit."""
    from pydantic_ai.exceptions import ModelHTTPError

    ctx = _LoopCtx(session, provider, model, base_url, api_key_env)

    while True:
        try:
            user_input = console.input(
                "\n[bold]Refine[/bold]: describe a change, [bold]:help[/bold] for commands,"
                " Enter to save, [bold]:quit[/bold] to discard > "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not user_input or user_input.lower() == "save":
            return turn
        if user_input.lower() in ("quit", "q"):
            return None

        # Colon-commands (and the '?' help alias) -- deterministic, no LLM.
        if user_input == "?" or user_input.startswith(":"):
            signal = _handle_command(user_input, ctx)
            if signal == _CMD_SAVE:
                return turn
            if signal == _CMD_QUIT:
                return None
            turn = session.current_turn()  # refresh; preserves the tailored test prompt
            continue

        # Plain text -> AI refine. Guard when no key is configured.
        if not ai_available:
            console.print(
                "[yellow]No API key configured for AI refinement.[/yellow] Use [bold]:[/bold]"
                " commands to edit, [bold]:model[/bold] to set a model, or run"
                " [bold]initrunner setup[/bold]. Empty line saves."
            )
            continue

        prev_yaml = session.yaml_text
        with console.status("Refining..."):
            try:
                turn = session.refine(
                    user_input, provider, model, base_url=base_url, api_key_env=api_key_env
                )
            except ModelHTTPError as e:
                _handle_builder_error(e, provider, fatal=False)
                continue
            except Exception as e:
                console.print(f"[red]Error during refinement:[/red] {e}")
                continue

        # Inject base_url/api_key_env into refined YAML
        if base_url:
            from initrunner.services.agent_builder import rewrite_model_block

            session.yaml_text = rewrite_model_block(
                session.yaml_text, base_url=base_url, api_key_env=api_key_env
            )

        _display_turn(turn, session)
        _print_change_summary(prev_yaml, session.yaml_text)


def _scaffold_tool(output: Path, provider: str) -> None:
    """Scaffold a custom tool Python module."""
    from initrunner.services.agent_builder import sanitize_module_stem
    from initrunner.templates import template_tool

    py_name = sanitize_module_stem(output.stem)
    out_path = Path(f"{py_name}.py")
    if out_path.exists():
        console.print(f"[red]Error:[/red] {out_path} already exists.")
        raise typer.Exit(1)
    content = template_tool(py_name, provider)
    out_path.write_text(content)
    console.print(f"[green]Created[/green] {out_path}")
    console.print(
        "[dim]Tip: 'initrunner tool new \"<description>\"' scaffolds a tool from a"
        " description with AI.[/dim]"
    )
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Edit {out_path} to add your tool functions")
    console.print("  2. Reference in role.yaml:")
    console.print("     tools:")
    console.print("       - type: custom")
    console.print(f"         module: {py_name}")


def _scaffold_skill(output: Path) -> None:
    """Scaffold a skill directory with SKILL.md."""
    from initrunner.templates import template_skill

    name = output.stem
    skill_dir_path = Path(name)
    skill_file = skill_dir_path / "SKILL.md"
    if skill_dir_path.exists():
        console.print(f"[red]Error:[/red] {skill_dir_path} already exists.")
        raise typer.Exit(1)
    skill_dir_path.mkdir(parents=True)
    content = template_skill(name, "openai")
    skill_file.write_text(content)
    console.print(f"[green]Created[/green] {skill_file}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Edit {skill_file} to configure tools and prompt")
    console.print("  2. Reference in role.yaml:")
    console.print("     skills:")
    console.print(f"       - {name}")
