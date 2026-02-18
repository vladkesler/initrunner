"""Interactive wizard for role.yaml creation."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from initrunner.cli._helpers import check_ollama_running, console

_PROVIDERS = ["openai", "anthropic", "google", "groq", "mistral", "cohere", "ollama"]


def run_wizard() -> None:
    """Launch the interactive role creation wizard."""
    from initrunner.templates import (
        TOOL_DESCRIPTIONS,
        TOOL_PROMPT_FIELDS,
        WIZARD_TEMPLATES,
        build_role_yaml,
    )

    console.print(
        Panel(
            "[bold]Create a new agent role[/bold]\n"
            "Answer the prompts below to generate a role.yaml file.",
            title="InitRunner Wizard",
            border_style="cyan",
        )
    )

    # --- Agent name ---
    name = Prompt.ask("Agent name", default="my-agent")

    # --- Description ---
    description = Prompt.ask("Description (optional)", default="")

    # --- Provider ---
    console.print()
    for i, prov in enumerate(_PROVIDERS, 1):
        default_tag = " (default)" if prov == "openai" else ""
        console.print(f"  {i}. {prov}{default_tag}")
    provider = Prompt.ask(
        "Provider",
        choices=_PROVIDERS,
        default="openai",
    )

    if provider == "ollama":
        check_ollama_running()

    # --- Model selection ---
    from initrunner.cli._helpers import prompt_model_selection

    ollama_models = None
    if provider == "ollama":
        try:
            from initrunner.cli.setup_cmd import _check_ollama_models

            ollama_models = _check_ollama_models() or None
        except Exception:
            pass  # fall back to static PROVIDER_MODELS["ollama"]

    model_name = prompt_model_selection(provider, ollama_models=ollama_models)

    # --- Base template ---
    console.print()
    console.print("[bold]Base template:[/bold]")
    template_keys = list(WIZARD_TEMPLATES.keys())
    for i, (key, desc) in enumerate(WIZARD_TEMPLATES.items(), 1):
        console.print(f"  {i}. {key:10s} — {desc}")

    template_choice = Prompt.ask(
        "Template",
        choices=template_keys,
        default="basic",
    )

    # Pre-populate features based on template
    enable_memory = template_choice == "memory"
    enable_ingest = template_choice == "rag"
    tools: list[dict] = []
    triggers: list[dict] = []
    system_prompt = "You are a helpful assistant."

    if template_choice == "memory":
        system_prompt = (
            "You are a helpful assistant with long-term memory.\n"
            "Use the remember() tool to save important information.\n"
            "Use the recall() tool to search your memories before answering."
        )
    elif template_choice == "rag":
        system_prompt = (
            "You are a knowledge assistant. Use search_documents to find relevant\n"
            "content before answering. Always cite your sources."
        )
    elif template_choice == "daemon":
        system_prompt = "You are a monitoring assistant that responds to events."
        triggers = [
            {
                "type": "file_watch",
                "paths": ["./watched"],
                "extensions": [".md", ".txt"],
                "prompt_template": "File changed: {path}. Summarize the changes.",
            }
        ]

    # --- Tool selection ---
    available_tools = list(TOOL_DESCRIPTIONS.keys())
    console.print()
    console.print(
        "[bold]Add tools?[/bold] (enter tool numbers separated by comma, or press Enter to skip)"
    )
    for i, tool_type in enumerate(available_tools, 1):
        desc = TOOL_DESCRIPTIONS[tool_type]
        console.print(f"  {i:2d}. {tool_type:12s} — {desc}")

    tool_input = Prompt.ask("Tools (e.g. 1,3,5)", default="")
    selected_tools: list[str] = []
    if tool_input.strip():
        for part in tool_input.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(available_tools):
                    selected_tools.append(available_tools[idx])
            elif part in available_tools:
                selected_tools.append(part)

    # --- Configure each selected tool ---
    for tool_type in selected_tools:
        tool_config: dict = {"type": tool_type}
        fields = TOOL_PROMPT_FIELDS.get(tool_type, [])

        for field_name, prompt_text, default in fields:
            value = Prompt.ask(f"  {tool_type} — {prompt_text}", default=default)

            # Convert boolean strings
            if value.lower() in ("true", "yes", "y"):
                tool_config[field_name] = True
            elif value.lower() in ("false", "no", "n"):
                tool_config[field_name] = False
            else:
                # Try integer
                try:
                    tool_config[field_name] = int(value)
                except ValueError:
                    tool_config[field_name] = value

        tools.append(tool_config)

    if selected_tools:
        console.print(f"  [dim]Selected: {', '.join(selected_tools)}[/dim]")

    # --- Memory ---
    if not enable_memory:
        console.print()
        if typer.confirm("Enable memory?", default=False):
            enable_memory = True

    # --- Ingestion ---
    ingest = None
    if not enable_ingest:
        console.print()
        if typer.confirm("Enable ingestion (RAG)?", default=False):
            enable_ingest = True

    if enable_ingest:
        sources = Prompt.ask("  Ingest sources glob", default="./docs/**/*.md")
        ingest = {
            "sources": [sources],
            "chunking": {
                "strategy": "fixed",
                "chunk_size": 512,
                "chunk_overlap": 50,
            },
        }

    # --- Embedding key warning for Anthropic ---
    if provider == "anthropic" and (enable_memory or enable_ingest):
        console.print()
        console.print(
            "[bold yellow]Warning:[/bold yellow] Anthropic does not provide an embeddings API. "
            "RAG and memory features require [bold]OPENAI_API_KEY[/bold] for embeddings.\n"
            "You can override this in your role.yaml under "
            "[bold]spec.ingest.embeddings[/bold] or [bold]spec.memory.embeddings[/bold]."
        )

    # --- Output file ---
    console.print()
    output_str = Prompt.ask("Output file", default="role.yaml")
    output = Path(output_str)

    if output.exists():
        if not typer.confirm(f"{output} already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()

    # --- Build and write ---
    yaml_content = build_role_yaml(
        name=name,
        description=description,
        provider=provider,
        model_name=model_name,
        system_prompt=system_prompt,
        tools=tools or None,
        memory=enable_memory,
        ingest=ingest,
        triggers=triggers or None,
    )

    # Validate before writing
    import yaml

    from initrunner.agent.schema.role import RoleDefinition

    try:
        raw = yaml.safe_load(yaml_content)
        RoleDefinition.model_validate(raw)
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Generated YAML has issues: {e}")
        console.print("[dim]Writing anyway — run 'initrunner validate' to debug.[/dim]")

    output.write_text(yaml_content)
    console.print(f"[green]Created[/green] {output}")
    console.print(f"[dim]Run: initrunner validate {output}[/dim]")
