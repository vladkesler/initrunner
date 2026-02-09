"""YAML persistence helpers for role detail editing."""

from __future__ import annotations

from pathlib import Path

import yaml


def save_yaml_field(path: Path, dotted_key: str, values: dict[str, object]) -> None:
    """Read a YAML file, merge *values* into *dotted_key*, and write it back."""
    data = yaml.safe_load(path.read_text()) or {}
    keys = dotted_key.split(".")
    target = data
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    leaf = keys[-1]
    if leaf not in target or not isinstance(target[leaf], dict):
        target[leaf] = {}
    target[leaf].update(values)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def save_yaml_field_scalar(path: Path, dotted_key: str, value: object) -> None:
    """Read a YAML file, set *dotted_key* to a scalar *value*, and write it back."""
    data = yaml.safe_load(path.read_text()) or {}
    keys = dotted_key.split(".")
    target = data
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    target[keys[-1]] = value
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def save_yaml_list_item(path: Path, list_key: str, index: int, values: dict[str, object]) -> None:
    """Read a YAML file, merge *values* into ``list_key[index]``, write back."""
    data = yaml.safe_load(path.read_text()) or {}
    keys = list_key.split(".")
    target = data
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    leaf = keys[-1]
    lst = target.get(leaf)
    if not isinstance(lst, list) or index >= len(lst):
        return
    if not isinstance(lst[index], dict):
        lst[index] = {}
    lst[index].update(values)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
