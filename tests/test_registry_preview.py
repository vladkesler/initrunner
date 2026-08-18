"""Security warnings shown before installing role bundles."""

from pathlib import Path

from initrunner.registry._preview import _detect_code_exec_warnings


def test_code_exec_warnings_cover_flat_tool_shorthand(tmp_path: Path) -> None:
    (tmp_path / "agent.yaml").write_text(
        "name: unsafe-agent\n"
        "prompt: hi\n"
        "tools:\n"
        "  - shell\n"
        "  - python: {}\n"
        "  - mcp:\n"
        "      command: local-server\n"
    )

    warnings = _detect_code_exec_warnings(tmp_path)

    assert len(warnings) == 1
    assert "shell" in warnings[0]
    assert "python" in warnings[0]
    assert "mcp(command)" in warnings[0]


def test_code_exec_warnings_still_cover_envelope_tools(tmp_path: Path) -> None:
    (tmp_path / "role.yaml").write_text(
        "apiVersion: initrunner/v1\n"
        "kind: Agent\n"
        "metadata:\n"
        "  name: unsafe-agent\n"
        "spec:\n"
        "  role: hi\n"
        "  tools:\n"
        "    - type: plugin\n"
    )

    warnings = _detect_code_exec_warnings(tmp_path)

    assert len(warnings) == 1
    assert "plugin" in warnings[0]
