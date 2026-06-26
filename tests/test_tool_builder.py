"""Tests for the custom-tool scaffold service (initrunner tool new)."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from initrunner.services.tool_builder import (
    ToolScaffold,
    _extract_python_blocks,
    build_custom_tool_reference,
    scaffold_tool,
    write_scaffold,
)

_VALID = '''Module: fetch_pr_diff

Fetches the unified diff for a GitHub pull request.

```python
import urllib.request


async def fetch_pr_diff(owner: str, repo: str, number: int) -> str:
    """Fetch the unified diff for a GitHub pull request."""
    url = f"https://github.com/{owner}/{repo}/pull/{number}.diff"
    return url
```

```python
def test_builds_url():
    assert True
```
'''

_BAD = '''Module: bad_tool

Uses a blocked import.

```python
import os


async def run() -> str:
    """Return the working directory."""
    return os.getcwd()
```

```python
def test_x():
    assert True
```
'''


def _result(output: str) -> MagicMock:
    r = MagicMock()
    r.output = output
    r.all_messages.return_value = []
    return r


@contextmanager
def _patched_agent(*outputs: str):
    """Patch the model build + Agent so run_sync yields the given outputs in order."""
    with (
        patch("initrunner.agent.loader._build_model", return_value=MagicMock()),
        patch("pydantic_ai.Agent") as agent_cls,
    ):
        instance = agent_cls.return_value
        instance.run_sync.side_effect = [_result(o) for o in outputs]
        yield instance


class TestExtractBlocks:
    def test_splits_explanation_and_two_blocks(self):
        explanation, module, test = _extract_python_blocks(_VALID)
        assert "Module: fetch_pr_diff" in explanation
        assert "async def fetch_pr_diff" in module
        assert "def test_builds_url" in test


class TestScaffoldTool:
    def test_happy_path_validates_and_names(self):
        with _patched_agent(_VALID):
            scaffold = scaffold_tool("fetch a github pr diff", "openai")
        assert scaffold.warnings == []
        assert scaffold.function_names == ["fetch_pr_diff"]
        assert scaffold.module_name == "fetch_pr_diff"
        assert "type: custom" in scaffold.yaml_snippet
        assert "module: fetch_pr_diff" in scaffold.yaml_snippet

    def test_does_not_import_the_module(self):
        with _patched_agent(_VALID):
            scaffold_tool("fetch a github pr diff", "openai")
        # Scaffolding only AST-parses; it must never import the generated module.
        assert "fetch_pr_diff" not in sys.modules

    def test_blocked_import_triggers_one_auto_repair(self):
        with _patched_agent(_BAD, _VALID) as agent:
            scaffold = scaffold_tool("do a thing", "openai")
        assert agent.run_sync.call_count == 2  # original + exactly one repair
        assert scaffold.warnings == []
        assert scaffold.function_names == ["fetch_pr_diff"]

    def test_repair_failure_records_warning(self):
        with _patched_agent(_BAD, _BAD) as agent:
            scaffold = scaffold_tool("do a thing", "openai")
        assert agent.run_sync.call_count == 2
        assert scaffold.warnings  # validation failed after the single repair
        assert scaffold.function_names == []


class TestWriteScaffold:
    def test_writes_module_and_test(self, tmp_path):
        scaffold = ToolScaffold(
            module_name="t",
            module_source="x = 1\n",
            test_source="def test_x():\n    assert True\n",
            function_names=["t"],
            yaml_snippet="",
            explanation="",
        )
        written = write_scaffold(scaffold, tmp_path)
        assert (tmp_path / "t.py").read_text() == "x = 1\n"
        assert (tmp_path / "test_t.py").exists()
        assert len(written) == 2

    def test_refuses_overwrite_without_force(self, tmp_path):
        scaffold = ToolScaffold(
            module_name="t",
            module_source="x = 1\n",
            test_source="",
            function_names=[],
            yaml_snippet="",
            explanation="",
        )
        write_scaffold(scaffold, tmp_path)
        with pytest.raises(FileExistsError):
            write_scaffold(scaffold, tmp_path)
        write_scaffold(scaffold, tmp_path, force=True)  # force succeeds


class TestRetargetTestImports:
    def test_rewrites_import_to_final_module_name(self):
        from initrunner.services.tool_builder import _retarget_test_imports

        src = "from word_count_tool import count_word\n\ndef test_x():\n    assert True\n"
        out = _retarget_test_imports(src, "wordcount", ["count_word"])
        assert "from wordcount import count_word" in out
        assert "word_count_tool" not in out

    def test_leaves_unrelated_and_matching_imports(self):
        from initrunner.services.tool_builder import _retarget_test_imports

        src = "import pytest\nfrom wordcount import count_word\n"
        out = _retarget_test_imports(src, "wordcount", ["count_word"])
        assert "import pytest" in out
        assert "from wordcount import count_word" in out


def test_reference_lists_blocked_modules():
    ref = build_custom_tool_reference()
    assert "subprocess" in ref and "os" in ref
    assert "tool_config" in ref
