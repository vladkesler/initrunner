"""Load and validate flow YAML definitions."""

from __future__ import annotations

from pathlib import Path


class FlowLoadError(Exception):
    """Raised when a flow definition cannot be loaded or validated."""


def load_flow(path: Path):  # -> FlowDefinition
    """Read a YAML file and validate it as a FlowDefinition.

    Accepts ``kind: Flow`` envelopes and flat v3 documents with ``then`` edges.
    """
    from initrunner._yaml import load_raw_yaml
    from initrunner.agent.schema.adapt import AdaptError, document_to_flow, run_kind_from_mapping
    from initrunner.agent.schema.document import DocumentClass, classify_mapping
    from initrunner.agent.schema.normalize import NormalizeError, normalize_mapping
    from initrunner.deprecations import validate_flow_dict

    raw = load_raw_yaml(path, FlowLoadError)
    try:
        if classify_mapping(raw).document_class is DocumentClass.FLAT_AGENT:
            if run_kind_from_mapping(raw) != "Flow":
                raise FlowLoadError(f"{path} is not a graph agent")
            return document_to_flow(normalize_mapping(raw).document, base_dir=path.parent)
        flow, _hits = validate_flow_dict(raw)
    except (AdaptError, NormalizeError, ValueError, Exception) as e:
        raise FlowLoadError(f"Validation failed for {path}:\n{e}") from e
    return flow
