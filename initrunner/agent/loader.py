"""Load role.yaml and construct PydanticAI agents."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from initrunner._compat import require_provider
from initrunner._yaml import load_yaml_model
from initrunner.agent.schema import ModelConfig, RoleDefinition

logger = logging.getLogger(__name__)

_PROVIDER_API_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
}


class RoleLoadError(Exception):
    """Raised when a role definition cannot be loaded or validated."""


def load_role(path: Path) -> RoleDefinition:
    """Read a YAML file and validate it as a RoleDefinition."""
    return load_yaml_model(path, RoleDefinition, RoleLoadError)


def _build_model(model_config: ModelConfig):
    """Build a PydanticAI model — string for standard providers, OpenAIChatModel for custom."""
    if not model_config.needs_custom_provider():
        env_var = model_config.api_key_env or _PROVIDER_API_KEY_ENVS.get(model_config.provider)
        if env_var and not os.environ.get(env_var):
            raise RoleLoadError(
                f"API key not found. Set the {env_var} environment variable:\n"
                f"  export {env_var}=your-key-here\n"
                f"Or add it to a .env file in your role directory or ~/.initrunner/.env"
            )
        return model_config.to_model_string()

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    base_url = model_config.base_url
    if model_config.provider == "ollama":
        base_url = base_url or "http://localhost:11434/v1"
        api_key = "ollama"
    elif model_config.api_key_env:
        api_key = os.environ.get(model_config.api_key_env)
        if not api_key:
            raise RoleLoadError(
                f"Environment variable '{model_config.api_key_env}' is not set "
                f"(required by model config)"
            )
    else:
        api_key = None

    if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
        if Path("/.dockerenv").exists():
            logger.warning(
                "Detected Docker environment with localhost base_url '%s'. "
                "Consider using 'http://host.docker.internal:11434/v1' instead.",
                base_url,
            )

    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_config.name, provider=provider)


def _validate_provider(role: RoleDefinition) -> None:
    """Check the provider SDK is installed, raising RoleLoadError if not."""
    try:
        require_provider(role.spec.model.provider)
    except RuntimeError as e:
        raise RoleLoadError(str(e)) from None


def _resolve_skills_and_merge(
    role: RoleDefinition,
    role_dir: Path | None,
    extra_skill_dirs: list[Path] | None,
) -> tuple[str, list]:
    """Resolve skills, log warnings, merge tools, and compose the system prompt.

    Returns ``(system_prompt, all_tools)``.
    """
    system_prompt = role.spec.role
    all_tools = list(role.spec.tools)

    if not role.spec.skills:
        return system_prompt, all_tools

    from initrunner.agent.skills import (
        build_skill_system_prompt,
        merge_skill_tools,
        resolve_skills,
    )

    resolved_skills = resolve_skills(role.spec.skills, role_dir, extra_skill_dirs)

    for rs in resolved_skills:
        for req in rs.requirement_statuses:
            if not req.met:
                logger.warning(
                    "Skill '%s': unmet %s — %s",
                    rs.definition.frontmatter.name,
                    req.kind,
                    req.detail,
                )

    all_tools = merge_skill_tools(resolved_skills, role.spec.tools)
    skill_prompt = build_skill_system_prompt(resolved_skills)
    if skill_prompt:
        system_prompt = f"{role.spec.role}\n\n{skill_prompt}"

    return system_prompt, all_tools


def _create_agent(
    role: RoleDefinition,
    system_prompt: str,
    toolsets: list,
    output_type: type,
    instrument: Any = None,
) -> Agent:
    """Build the model and construct the PydanticAI Agent."""
    kwargs: dict[str, Any] = {
        "output_type": output_type,
        "system_prompt": system_prompt,
        "model_settings": ModelSettings(
            temperature=role.spec.model.temperature,
            max_tokens=role.spec.model.max_tokens,
        ),
        "toolsets": toolsets if toolsets else None,
    }
    if instrument is not None:
        kwargs["instrument"] = instrument
    return Agent(_build_model(role.spec.model), **kwargs)


def build_agent(
    role: RoleDefinition,
    role_dir: Path | None = None,
    output_type: type | None = None,
    extra_skill_dirs: list[Path] | None = None,
) -> Agent:
    """Construct a PydanticAI Agent from a validated RoleDefinition."""
    _validate_provider(role)
    system_prompt, all_tools = _resolve_skills_and_merge(role, role_dir, extra_skill_dirs)

    # Resolve output type: explicit param wins, then role config, then str default
    if output_type is None:
        from initrunner.agent.output import resolve_output_type

        output_type = resolve_output_type(role.spec.output, role_dir)

    from initrunner.agent.tools import build_toolsets

    toolsets = build_toolsets(all_tools, role, role_dir=role_dir)

    instrument = None
    if role.spec.observability is not None:
        from initrunner.observability import get_instrumentation_settings

        instrument = get_instrumentation_settings(role.spec.observability)

    agent = _create_agent(role, system_prompt, toolsets, output_type, instrument=instrument)

    # Register dynamic system prompt for procedural memory injection
    if role.spec.memory is not None and role.spec.memory.procedural.enabled:
        from initrunner.agent.memory_ops import build_memory_system_prompt

        @agent.system_prompt
        def _procedural_context() -> str:
            return build_memory_system_prompt(role)

    return agent


def _load_dotenv(role_dir: Path) -> None:
    """Load .env files — local first, then global as fallback.

    Uses ``override=False`` so existing env vars always win.
    Local is loaded before global so project-local values take precedence.
    """
    from dotenv import load_dotenv

    local_env = role_dir / ".env"
    if local_env.is_file():
        load_dotenv(local_env, override=False)
    from initrunner.config import get_global_env_path

    global_env = get_global_env_path()
    if global_env.is_file():
        load_dotenv(global_env, override=False)


def load_and_build(
    path: Path,
    extra_skill_dirs: list[Path] | None = None,
) -> tuple[RoleDefinition, Agent]:
    """Load a role YAML and build the corresponding agent."""
    _load_dotenv(path.parent)
    role = load_role(path)
    agent = build_agent(role, role_dir=path.parent, extra_skill_dirs=extra_skill_dirs)
    return role, agent
