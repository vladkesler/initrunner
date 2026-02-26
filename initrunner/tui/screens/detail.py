"""RoleDetailScreen — hub showing full role configuration with action shortcuts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Static

from initrunner.tui.screens.base import RoleScreen
from initrunner.tui.screens.detail_fields import (
    convert_values,
    guardrails_fields,
    ingest_fields,
    memory_fields,
    model_fields,
    sink_fields,
    tool_fields,
    trigger_fields,
)
from initrunner.tui.screens.detail_modals import (
    FieldEditModal,
    SectionPickerModal,
    TextEditModal,
)
from initrunner.tui.screens.detail_yaml import (
    save_yaml_field,
    save_yaml_field_scalar,
    save_yaml_list_item,
)
from initrunner.tui.theme import COLOR_SECONDARY

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from initrunner.agent.schema.role import RoleDefinition


# ── Screen ───────────────────────────────────────────────────


class RoleDetailScreen(RoleScreen):
    """Role configuration overview with action shortcuts."""

    SUB_TITLE = "Role Detail"

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("enter", "edit_section", "Edit", show=True),
        Binding("r", "run_chat", "Run", show=True),
        Binding("v", "validate", "Validate", show=True),
        Binding("i", "ingest", "Ingest", show=True),
        Binding("d", "daemon", "Daemon", show=True),
        Binding("m", "memory", "Memory", show=True),
        Binding("e", "view_yaml", "View YAML", show=True),
    ]

    _role_path: Path

    def __init__(self, *, role_path: Path, role: RoleDefinition) -> None:
        super().__init__(role_path=role_path, role=role)

    def compose_content(self) -> ComposeResult:
        yield Static(self._build_status_bar(), id="detail-status-bar")
        with VerticalScroll(id="detail-scroll"):
            yield from self._build_sections()

    def _build_sections(self) -> ComposeResult:
        # Always show Model
        yield Static(self._build_model_section(), classes="detail-section")
        # System Prompt collapsible
        yield from self._build_system_prompt_section()
        # Only yield configured sections
        if self._role.spec.tools:
            yield Static(self._build_tools_section(), classes="detail-section")
        if self._role.spec.triggers:
            yield Static(self._build_triggers_section(), classes="detail-section")
        if self._role.spec.sinks:
            yield Static(self._build_sinks_section(), classes="detail-section")
        if self._role.spec.ingest:
            yield Static(self._build_ingest_section(), classes="detail-section")
        if self._role.spec.memory:
            yield Static(self._build_memory_section(), classes="detail-section")
        # Always show Guardrails
        yield Static(self._build_guardrails_section(), classes="detail-section")
        # Security only if non-default
        security_text = self._build_security_section()
        if security_text:
            yield Static(security_text, classes="detail-section")
        # Compact unconfigured summary
        unconfigured = self._build_unconfigured_summary()
        if unconfigured:
            yield Static(unconfigured, id="unconfigured-summary")

    def on_mount(self) -> None:
        super().on_mount()
        self.sub_title = f"Role Detail — {self._role.metadata.name}"

    # ── Section builders ─────────────────────────────────────

    def _build_status_bar(self) -> str:
        role = self._role
        tags = ", ".join(role.metadata.tags) if role.metadata.tags else ""
        tag_part = f" │ tags: {tags}" if tags else ""
        desc = role.metadata.description
        desc_part = f" │ {desc}" if desc else ""
        return (
            f"[bold]{role.metadata.name}[/bold]"
            f" │ {role.spec.model.to_model_string()}"
            f"{tag_part}{desc_part}"
        )

    def _build_model_section(self) -> str:
        model = self._role.spec.model
        lines = [f"[bold {COLOR_SECONDARY}]── Model ──[/]"]
        lines.append(f"  Provider      {model.provider}")
        lines.append(f"  Name          {model.name}")
        temp = f"{model.temperature}"
        tokens = f"{model.max_tokens:,}"
        lines.append(f"  Temperature   {temp:<14}Max Tokens  {tokens}")
        if model.base_url:
            lines.append(f"  Base URL      {model.base_url}")
        return "\n".join(lines)

    def _build_system_prompt_section(self) -> ComposeResult:
        prompt = self._role.spec.role
        if prompt:
            yield Collapsible(
                Static(prompt, markup=False),
                title="System Prompt",
                collapsed=True,
            )

    def _build_tools_section(self) -> str:
        tools = self._role.spec.tools
        lines = [f"[bold {COLOR_SECONDARY}]── Tools ({len(tools)}) ──[/]"]
        for t in tools:
            lines.append(f"  {t.summary()}")
        return "\n".join(lines)

    def _build_triggers_section(self) -> str:
        triggers = self._role.spec.triggers
        lines = [f"[bold {COLOR_SECONDARY}]── Triggers ({len(triggers)}) ──[/]"]
        for t in triggers:
            lines.append(f"  {t.summary()}")
        return "\n".join(lines)

    def _build_sinks_section(self) -> str:
        sinks = self._role.spec.sinks
        lines = [f"[bold {COLOR_SECONDARY}]── Sinks ({len(sinks)}) ──[/]"]
        for s in sinks:
            lines.append(f"  {s.summary()}")
        return "\n".join(lines)

    def _build_ingest_section(self) -> str:
        ingest = self._role.spec.ingest
        assert ingest is not None
        lines = [f"[bold {COLOR_SECONDARY}]── Ingest ──[/]"]
        sources = ", ".join(ingest.sources)
        if len(sources) > 60:
            sources = sources[:57] + "..."
        lines.append(f"  Sources       {sources}")
        ch = ingest.chunking
        lines.append(
            f"  Chunking      {ch.strategy}, {ch.chunk_size} tokens, {ch.chunk_overlap} overlap"
        )
        lines.append(f"  Store         {ingest.store_backend.value}")
        return "\n".join(lines)

    def _build_memory_section(self) -> str:
        mem = self._role.spec.memory
        assert mem is not None
        lines = [f"[bold {COLOR_SECONDARY}]── Memory ──[/]"]
        lines.append(f"  Store         {mem.store_backend.value}")
        lines.append(f"  Max Sessions  {mem.max_sessions:<14}Max Memories    {mem.max_memories}")
        lines.append(f"  Resume Msgs   {mem.max_resume_messages}")
        return "\n".join(lines)

    def _build_guardrails_section(self) -> str:
        g = self._role.spec.guardrails
        lines = [f"[bold {COLOR_SECONDARY}]── Guardrails ──[/]"]
        lines.append(
            f"  Max Tokens    {g.max_tokens_per_run:,}{'':8}Timeout     {g.timeout_seconds}s"
        )
        lines.append(f"  Max Calls     {g.max_tool_calls:<14}Requests    {g.max_request_limit}")
        return "\n".join(lines)

    def _build_security_section(self) -> str:
        from initrunner.agent.schema.security import SecurityPolicy

        sec = self._role.spec.security
        defaults = SecurityPolicy()

        non_defaults: list[str] = []
        if sec.content.profanity_filter:
            non_defaults.append("profanity_filter=on")
        if sec.content.blocked_input_patterns:
            non_defaults.append(f"blocked_inputs={len(sec.content.blocked_input_patterns)}")
        if sec.content.blocked_output_patterns:
            non_defaults.append(f"blocked_outputs={len(sec.content.blocked_output_patterns)}")
        if sec.content.pii_redaction:
            non_defaults.append("pii_redaction=on")
        if sec.content.llm_classifier_enabled:
            non_defaults.append("llm_classifier=on")
        if sec.tools.audit_hooks_enabled:
            non_defaults.append("audit_hooks=on")
        if sec.server.require_https:
            non_defaults.append("require_https=on")
        if sec.rate_limit != defaults.rate_limit:
            non_defaults.append(f"rate_limit={sec.rate_limit.requests_per_minute}rpm")

        if not non_defaults:
            return ""

        lines = [f"[bold {COLOR_SECONDARY}]── Security ──[/]"]
        for item in non_defaults:
            lines.append(f"  {item}")
        return "\n".join(lines)

    def _build_unconfigured_summary(self) -> str:
        features: list[str] = []
        if not self._role.spec.tools:
            features.append("Tools")
        if not self._role.spec.triggers:
            features.append("Triggers")
        if not self._role.spec.sinks:
            features.append("Sinks")
        if self._role.spec.ingest is None:
            features.append("Ingest")
        if self._role.spec.memory is None:
            features.append("Memory")
        if not features:
            return ""
        return f"[dim]Not configured: {', '.join(features)}[/]"

    # ── Refresh ───────────────────────────────────────────────

    async def _refresh_content(self) -> None:
        scroll = self.query_one("#detail-scroll", VerticalScroll)
        await scroll.remove_children()
        await scroll.mount(*list(self._build_sections()))

        # Update status bar and sub_title
        self.query_one("#detail-status-bar", Static).update(self._build_status_bar())
        self.sub_title = f"Role Detail — {self._role.metadata.name}"

    # ── Actions ──────────────────────────────────────────────

    def action_edit_section(self) -> None:
        sections: list[tuple[str, str]] = [
            ("model", "Model"),
            ("system_prompt", "System Prompt"),
            ("guardrails", "Guardrails"),
        ]
        if self._role.spec.tools:
            sections.append(("tools", f"Tools ({len(self._role.spec.tools)})"))
        if self._role.spec.triggers:
            sections.append(("triggers", f"Triggers ({len(self._role.spec.triggers)})"))
        if self._role.spec.sinks:
            sections.append(("sinks", f"Sinks ({len(self._role.spec.sinks)})"))
        if self._role.spec.ingest:
            sections.append(("ingest", "Ingest"))
        if self._role.spec.memory:
            sections.append(("memory", "Memory"))
        self.app.push_screen(
            SectionPickerModal(sections),
            callback=self._on_section_picked,
        )

    def _on_section_picked(self, key: str | None) -> None:
        if key is None:
            return
        if key == "model":
            self.app.push_screen(
                FieldEditModal("Edit Model", model_fields(self._role)),
                callback=self._on_model_saved,
            )
        elif key == "guardrails":
            self.app.push_screen(
                FieldEditModal("Edit Guardrails", guardrails_fields(self._role)),
                callback=self._on_guardrails_saved,
            )
        elif key == "system_prompt":
            self.app.push_screen(
                TextEditModal("Edit System Prompt", self._role.spec.role),
                callback=self._on_system_prompt_saved,
            )
        elif key == "ingest":
            self.app.push_screen(
                FieldEditModal("Edit Ingest", ingest_fields(self._role)),
                callback=self._on_ingest_saved,
            )
        elif key == "memory":
            self.app.push_screen(
                FieldEditModal("Edit Memory", memory_fields(self._role)),
                callback=self._on_memory_saved,
            )
        elif key in ("tools", "triggers", "sinks"):
            self._edit_list_section(key)

    def _edit_list_section(self, section: str) -> None:
        items: list[Any] = getattr(self._role.spec, section)
        if len(items) == 1:
            self._edit_list_item(section, 0)
        else:
            options = [(str(i), item.summary()) for i, item in enumerate(items)]
            self.app.push_screen(
                SectionPickerModal(options, title=f"Edit {section.title()}"),
                callback=lambda idx, s=section: self._on_list_item_picked(s, idx),
            )

    def _on_list_item_picked(self, section: str, idx_str: str | None) -> None:
        if idx_str is None:
            return
        self._edit_list_item(section, int(idx_str))

    def _edit_list_item(self, section: str, index: int) -> None:
        items: list[Any] = getattr(self._role.spec, section)
        item = items[index]
        if section == "tools":
            fields = tool_fields(item)
        elif section == "triggers":
            fields = trigger_fields(item)
        else:
            fields = sink_fields(item)
        type_label = getattr(item, "type", section)
        self.app.push_screen(
            FieldEditModal(f"Edit {section.title()} — {type_label}", fields),
            callback=lambda vals, s=section, i=index: self._on_list_item_saved(s, i, vals),
        )

    # ── Save handlers ────────────────────────────────────────

    def _on_model_saved(self, values: dict[str, str] | None) -> None:
        if values is None:
            return
        try:
            converted = convert_values(values, model_fields(self._role))
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error", markup=False)
            return
        model_data: dict[str, object] = {}
        for key, val in converted.items():
            if key == "base_url" and not val:
                continue
            model_data[key] = val
        save_yaml_field(self._role_path, "spec.model", model_data)
        self.run_worker(self._reload_role())

    def _on_guardrails_saved(self, values: dict[str, str] | None) -> None:
        if values is None:
            return
        try:
            converted = convert_values(values, guardrails_fields(self._role))
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error", markup=False)
            return
        save_yaml_field(self._role_path, "spec.guardrails", converted)
        self.run_worker(self._reload_role())

    def _on_system_prompt_saved(self, text: str | None) -> None:
        if text is None:
            return
        save_yaml_field_scalar(self._role_path, "spec.role", text)
        self.run_worker(self._reload_role())

    def _on_ingest_saved(self, values: dict[str, str] | None) -> None:
        if values is None:
            return
        try:
            specs = ingest_fields(self._role)
            converted = convert_values(values, specs)
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error", markup=False)
            return
        # Separate flat keys into top-level and nested chunking keys
        ingest_data: dict[str, object] = {}
        chunking_data: dict[str, object] = {}
        for key, val in converted.items():
            if key.startswith("chunking."):
                chunking_data[key.split(".", 1)[1]] = val
            else:
                ingest_data[key] = val
        if chunking_data:
            ingest_data["chunking"] = chunking_data
        save_yaml_field(self._role_path, "spec.ingest", ingest_data)
        self.run_worker(self._reload_role())

    def _on_memory_saved(self, values: dict[str, str] | None) -> None:
        if values is None:
            return
        try:
            converted = convert_values(values, memory_fields(self._role))
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error", markup=False)
            return
        save_yaml_field(self._role_path, "spec.memory", converted)
        self.run_worker(self._reload_role())

    def _on_list_item_saved(self, section: str, index: int, values: dict[str, str] | None) -> None:
        if values is None:
            return
        items: list[Any] = getattr(self._role.spec, section)
        item = items[index]
        if section == "tools":
            specs = tool_fields(item)
        elif section == "triggers":
            specs = trigger_fields(item)
        else:
            specs = sink_fields(item)
        try:
            converted = convert_values(values, specs)
        except ValueError as exc:
            self.notify(f"Invalid value: {exc}", severity="error", markup=False)
            return
        save_yaml_list_item(self._role_path, f"spec.{section}", index, converted)
        self.run_worker(self._reload_role())

    async def _reload_role(self) -> None:
        from initrunner.tui.services import ServiceBridge

        result = await ServiceBridge.validate_role(self._role_path)
        if result.role is not None:
            self._role = result.role
            await self._refresh_content()
            self.notify("Saved", severity="information")
        else:
            self.notify(f"Save error: {result.error}", severity="error", markup=False)

    def action_run_chat(self) -> None:
        from initrunner.tui.screens.run import RunScreen

        self.app.push_screen(RunScreen(role_path=self._role_path, role=self._role))

    def action_validate(self) -> None:
        self.run_worker(self._validate_worker())

    async def _validate_worker(self) -> None:
        from initrunner.tui.services import ServiceBridge

        result = await ServiceBridge.validate_role(self._role_path)
        if result.role is not None:
            self.notify(f"{result.role.metadata.name}: Valid", severity="information")
        else:
            self.notify(f"{self._role_path.name}: {result.error}", severity="error", markup=False)

    def action_ingest(self) -> None:
        if self._role.spec.ingest is None:
            self.notify("No ingest config in this role", severity="warning")
            return
        from initrunner.tui.screens.ingest import IngestScreen

        self.app.push_screen(IngestScreen(role_path=self._role_path, role=self._role))

    def action_daemon(self) -> None:
        if not self._role.spec.triggers:
            self.notify("No triggers configured in this role", severity="warning")
            return
        from initrunner.tui.screens.daemon import DaemonScreen

        self.app.push_screen(DaemonScreen(role_path=self._role_path, role=self._role))

    def action_memory(self) -> None:
        if self._role.spec.memory is None:
            self.notify("No memory config in this role", severity="warning")
            return
        from initrunner.tui.screens.memory import MemoryScreen

        self.app.push_screen(MemoryScreen(role=self._role))

    def action_view_yaml(self) -> None:
        self.run_worker(self._view_yaml_worker())

    async def _view_yaml_worker(self) -> None:
        import asyncio

        content = await asyncio.to_thread(self._role_path.read_text)
        from initrunner.tui.screens.roles import YamlViewerModal

        self.app.push_screen(YamlViewerModal(content, title=self._role_path.name))
