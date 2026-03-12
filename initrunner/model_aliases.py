"""Model alias resolution: ~/.initrunner/models.yaml support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)


class ModelAliasConfig(BaseModel):
    """Schema for ``~/.initrunner/models.yaml``."""

    aliases: dict[str, str] = {}


def load_model_aliases() -> dict[str, str]:
    """Load alias map from ``~/.initrunner/models.yaml``.

    Returns ``{}`` on missing or broken file.  Warns on parse errors.
    Validates that every alias target contains at least one ``:`` separator.
    """
    from initrunner.config import get_models_config_path

    path = get_models_config_path()
    if not path.is_file():
        return {}

    try:
        import yaml

        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            return {}
        cfg = ModelAliasConfig.model_validate(data)
    except Exception:
        _logger.warning("Failed to load %s, using no aliases", path, exc_info=True)
        return {}

    # Validate alias targets
    valid: dict[str, str] = {}
    for alias, target in cfg.aliases.items():
        if ":" not in target:
            _logger.warning(
                "Invalid alias '%s' in %s: target '%s' must contain a ':' separator "
                "(e.g. 'openai:gpt-4o'). Skipping.",
                alias,
                path,
                target,
            )
            continue
        valid[alias] = target

    return valid


def resolve_model_alias(name_or_alias: str, aliases: dict[str, str] | None = None) -> str:
    """Resolve a model alias to its ``provider:model`` target.

    Returns the input unchanged if it is not an alias (i.e. already contains
    a colon or is not found in the alias map).

    When *aliases* is ``None``, loads from disk via :func:`load_model_aliases`.
    """
    if ":" in name_or_alias:
        return name_or_alias

    if aliases is None:
        aliases = load_model_aliases()

    return aliases.get(name_or_alias, name_or_alias)


def parse_model_string(model_string: str) -> tuple[str, str]:
    """Split ``provider:model`` on the first colon.

    Returns ``(provider, model_name)``.  Additional colons stay in the model
    name (e.g. ``ollama:llama3.2:latest`` → ``("ollama", "llama3.2:latest")``).

    Raises :class:`ValueError` if *model_string* contains no colon.
    """
    if ":" not in model_string:
        raise ValueError(
            f"Invalid model string '{model_string}': expected 'provider:model' format. "
            f"Check your ~/.initrunner/models.yaml aliases or use 'provider:model' directly."
        )
    provider, name = model_string.split(":", 1)
    return provider, name
