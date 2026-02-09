"""Custom tools module for InitRunner.

All public functions are auto-discovered as agent tools. Type annotations and
docstrings are used as tool schemas and descriptions. Functions accepting a
``tool_config`` parameter receive the config dict from role.yaml (hidden from
the LLM).

Run from the custom-tools-demo directory so InitRunner can import this module:
    cd examples/roles/custom-tools-demo
    initrunner run custom-tools-demo.yaml -i
"""

import hashlib
import json
import uuid


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a numeric value between common measurement units.

    Supported conversions: km/mi, kg/lb, c/f, l/gal, m/ft, cm/in.
    """
    conversions: dict[tuple[str, str], float | None] = {
        ("km", "mi"): 0.621371,
        ("mi", "km"): 1.60934,
        ("kg", "lb"): 2.20462,
        ("lb", "kg"): 0.453592,
        ("c", "f"): None,
        ("f", "c"): None,
        ("l", "gal"): 0.264172,
        ("gal", "l"): 3.78541,
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
        ("cm", "in"): 0.393701,
        ("in", "cm"): 2.54,
    }

    key = (from_unit.lower(), to_unit.lower())
    if key == ("c", "f"):
        result = value * 9 / 5 + 32
    elif key == ("f", "c"):
        result = (value - 32) * 5 / 9
    elif key in conversions:
        result = value * conversions[key]  # type: ignore[unsupported-operator]
    else:
        return f"Unsupported conversion: {from_unit} -> {to_unit}"

    return f"{value} {from_unit} = {result:.4f} {to_unit}"


def generate_uuid() -> str:
    """Generate a random UUID v4 identifier."""
    return str(uuid.uuid4())


def format_json(text: str) -> str:
    """Pretty-print a JSON string with 2-space indentation."""
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"


def word_count(text: str) -> str:
    """Count words, characters, and lines in a text string."""
    words = len(text.split())
    chars = len(text)
    lines = text.count("\n") + 1 if text else 0
    return f"Words: {words}, Characters: {chars}, Lines: {lines}"


def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Hash text using the specified algorithm (md5, sha1, sha256, sha512)."""
    algo = algorithm.lower()
    if algo not in ("md5", "sha1", "sha256", "sha512"):
        return f"Unsupported algorithm: {algorithm}. Use md5, sha1, sha256, or sha512."
    h = hashlib.new(algo)
    h.update(text.encode())
    return f"{algo}:{h.hexdigest()}"


def lookup_with_config(query: str, tool_config: dict) -> str:
    """Look up a query using the configured prefix and source.

    The tool_config parameter is injected by InitRunner from the role YAML
    and is hidden from the LLM.
    """
    prefix = tool_config.get("prefix", "DEFAULT")
    source = tool_config.get("source", "unknown")
    return f"[{prefix}] Result for '{query}' from source '{source}'"
