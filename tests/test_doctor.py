"""Tests for initrunner doctor command."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from initrunner.cli.main import app

runner = CliRunner()


class TestDoctorConfigScan:
    def test_doctor_no_keys(self, monkeypatch):
        """Doctor with no API keys shows table with Missing entries."""
        # Clear all provider env vars
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Provider Status" in result.output

    def test_doctor_with_key(self, monkeypatch):
        """Doctor with OPENAI_API_KEY set shows 'Set' in output."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Set" in result.output
        assert "Ready" in result.output


class TestDoctorEmbeddingProviders:
    def test_embedding_section_displayed(self, monkeypatch):
        """Doctor should show an 'Embedding Providers' table."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Embedding Providers" in result.output

    def test_embedding_key_set_status(self, monkeypatch):
        """When OPENAI_API_KEY is set, embedding status for openai/anthropic shows 'Set'."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        for var in ("GROQ_API_KEY", "MISTRAL_API_KEY", "CO_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        # OPENAI_API_KEY appears in embedding section
        assert "OPENAI_API_KEY" in result.output

    def test_embedding_key_missing_status(self, monkeypatch):
        """When GOOGLE_API_KEY is missing, embedding status for google shows 'Missing'."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        for var in ("GROQ_API_KEY", "MISTRAL_API_KEY", "CO_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Missing" in result.output

    def test_anthropic_note_displayed(self, monkeypatch):
        """Doctor should show note about Anthropic using OpenAI embeddings."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Anthropic uses OpenAI embeddings" in result.output

    def test_ollama_no_key_needed(self, monkeypatch):
        """Ollama row should show 'No key needed'."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "No key needed" in result.output


class TestDoctorDocker:
    def test_docker_row_displayed(self, monkeypatch):
        """Doctor should show a 'docker' row in the provider status table."""
        for var in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
            "CO_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch(
                    "initrunner.agent.docker_sandbox.check_docker_available",
                    return_value=False,
                ):
                    result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "docker" in result.output.lower()


class TestDoctorQuickstart:
    def test_quickstart_success(self, monkeypatch):
        """--quickstart with mocked successful run shows pass message."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Hello!"
        mock_result.total_tokens = 15
        mock_result.duration_ms = 100

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch("initrunner.agent.loader.build_agent") as mock_build:
                    mock_build.return_value = MagicMock()
                    with patch("initrunner.agent.executor.execute_run") as mock_exec:
                        mock_exec.return_value = (mock_result, [])
                        result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 0
        assert "passed" in result.output

    def test_quickstart_failure(self, monkeypatch):
        """--quickstart with failed run exits with code 1."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "API key invalid"

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch("initrunner.agent.loader.build_agent") as mock_build:
                    mock_build.return_value = MagicMock()
                    with patch("initrunner.agent.executor.execute_run") as mock_exec:
                        mock_exec.return_value = (mock_result, [])
                        result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 1
        assert "failed" in result.output

    def test_quickstart_exception(self, monkeypatch):
        """--quickstart with exception exits with code 1."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                with patch(
                    "initrunner.agent.loader.build_agent",
                    side_effect=RuntimeError("SDK not found"),
                ):
                    result = runner.invoke(app, ["doctor", "--quickstart"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()


def _valid_role_yaml() -> str:
    return textwrap.dedent("""\
        apiVersion: initrunner/v1
        kind: Agent
        metadata:
          name: test-valid
          spec_version: 2
        spec:
          role: You are helpful.
          model:
            provider: openai
            name: gpt-5-mini
    """)


class TestDoctorRoleValidation:
    def test_clean_role(self, tmp_path: Path, monkeypatch):
        """Valid role shows 'valid and up to date'."""
        p = tmp_path / "role.yaml"
        p.write_text(_valid_role_yaml())

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "valid and up to date" in result.output

    def test_stale_version_note(self, tmp_path: Path, monkeypatch):
        """spec_version: 1 shows stale note but exits 0."""
        content = _valid_role_yaml().replace("spec_version: 2", "spec_version: 1")
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "is behind" in result.output

    def test_zvec_shows_auto_fixable(self, tmp_path: Path, monkeypatch):
        """Role with zvec shows auto-fixable in table and exits 0 (not a hard error)."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "DEP002" in result.output
        assert "auto-fixable" in result.output

    def test_max_memories_shows_auto_fixable(self, tmp_path: Path, monkeypatch):
        """Role with memory.max_memories shows auto-fixable and exits 0."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-maxmem
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              memory:
                max_memories: 500
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 0
        assert "DEP001" in result.output
        assert "auto-fixable" in result.output

    def test_yaml_parse_error(self, tmp_path: Path, monkeypatch):
        """Broken YAML shows parse error and exits 1."""
        p = tmp_path / "role.yaml"
        p.write_text(":\n  bad: [yaml\n")

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p)])

        assert result.exit_code == 1
        assert "Cannot read" in result.output or "Invalid YAML" in result.output

    def test_auto_fixable_does_not_block_quickstart(self, tmp_path: Path, monkeypatch):
        """--role with auto-fixable deprecations + --quickstart proceeds to smoke test."""
        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(p), "--quickstart"])

        assert "DEP002" in result.output
        assert "auto-fixable" in result.output
        # Auto-fixable errors should NOT block the quickstart smoke test
        assert "Running quickstart" in result.output


# ---------------------------------------------------------------------------
# Service layer: services/doctor.py
# ---------------------------------------------------------------------------


class TestDiagnoseProviders:
    def test_key_set_sdk_missing(self, monkeypatch):
        """Provider with key set but SDK unavailable has fixable_sdk=True."""
        from initrunner.services.doctor import diagnose_providers

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch(
            "initrunner._compat.require_provider",
            side_effect=RuntimeError("missing"),
        ):
            results = diagnose_providers()

        anthropic = next(d for d in results if d.provider == "anthropic")
        assert anthropic.fixable_sdk is True
        assert anthropic.fixable_key is False

    def test_sdk_available_no_key(self, monkeypatch):
        """Provider with SDK available but no key has fixable_key=True."""
        from initrunner.services.doctor import diagnose_providers

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("initrunner._compat.require_provider"):
            results = diagnose_providers()

        openai = next(d for d in results if d.provider == "openai")
        assert openai.fixable_key is True
        assert openai.fixable_sdk is False

    def test_both_set(self, monkeypatch):
        """Provider with key and SDK has neither fixable."""
        from initrunner.services.doctor import diagnose_providers

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with patch("initrunner._compat.require_provider"):
            results = diagnose_providers()

        openai = next(d for d in results if d.provider == "openai")
        assert openai.fixable_key is False
        assert openai.fixable_sdk is False


class TestDiagnoseRoleExtras:
    def test_search_tool_gap(self):
        """Role with search tool and ddgs missing reports gap."""
        from initrunner.services.doctor import diagnose_role_extras

        raw = {"spec": {"tools": [{"type": "search"}]}}
        with patch("initrunner.services.doctor._is_module_available", return_value=False):
            gaps = diagnose_role_extras(raw)

        assert any(g.extras_name == "search" for g in gaps)

    def test_telegram_trigger_gap(self):
        """Role with telegram trigger reports gap."""
        from initrunner.services.doctor import diagnose_role_extras

        raw = {"spec": {"triggers": [{"type": "telegram"}]}}
        with patch("initrunner.services.doctor._is_module_available", return_value=False):
            gaps = diagnose_role_extras(raw)

        assert any(g.extras_name == "telegram" for g in gaps)

    def test_observability_gap(self):
        """Role with observability section reports gap."""
        from initrunner.services.doctor import diagnose_role_extras

        raw = {"spec": {"observability": {"backend": "console"}}}
        with patch("initrunner.services.doctor._is_module_available", return_value=False):
            gaps = diagnose_role_extras(raw)

        assert any(g.extras_name == "observability" for g in gaps)

    def test_no_features_no_gaps(self):
        """Role with no special features has no gaps."""
        from initrunner.services.doctor import diagnose_role_extras

        raw = {"spec": {"role": "test", "model": {"provider": "openai", "name": "gpt-5-mini"}}}
        gaps = diagnose_role_extras(raw)
        assert gaps == []

    def test_deduplicates_extras(self):
        """Multiple tools needing the same extra produce one gap."""
        from initrunner.services.doctor import diagnose_role_extras

        raw = {"spec": {"tools": [{"type": "search"}, {"type": "web_reader"}]}}
        with patch("initrunner.services.doctor._is_module_available", return_value=False):
            gaps = diagnose_role_extras(raw)

        search_gaps = [g for g in gaps if g.extras_name == "search"]
        assert len(search_gaps) == 1


class TestBuildRoleFixPlan:
    def test_can_bump_clean_role(self):
        """Valid role with spec_version 1 and no deprecation hits can be bumped."""
        from initrunner.services.doctor import build_role_fix_plan

        raw = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test", "spec_version": 1},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
        plan = build_role_fix_plan(raw)
        assert plan.can_bump_spec_version is True
        assert plan.current_spec_version == 1

    def test_cannot_bump_with_deprecation_hits(self):
        """Role with deprecation hits cannot be bumped."""
        from initrunner.services.doctor import build_role_fix_plan

        raw = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test", "spec_version": 1},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
                "memory": {"max_memories": 500},
            },
        }
        plan = build_role_fix_plan(raw)
        assert plan.can_bump_spec_version is False

    def test_cannot_bump_with_schema_error(self):
        """Role with schema error cannot be bumped."""
        from initrunner.services.doctor import build_role_fix_plan

        raw = {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test", "spec_version": 1},
            "spec": {},  # missing required 'role' field
        }
        plan = build_role_fix_plan(raw)
        assert plan.can_bump_spec_version is False


class TestDeriveRoleProvider:
    def test_extracts_provider(self):
        """Derives provider and env var from spec.model."""
        from initrunner.services.doctor import derive_role_provider

        raw = {"spec": {"model": {"provider": "openai", "name": "gpt-5-mini"}}}
        result = derive_role_provider(raw)
        assert result == ("openai", "OPENAI_API_KEY")

    def test_honors_api_key_env(self):
        """Uses spec.model.api_key_env when set."""
        from initrunner.services.doctor import derive_role_provider

        raw = {
            "spec": {
                "model": {
                    "provider": "openai",
                    "name": "gpt-5-mini",
                    "api_key_env": "CUSTOM_KEY",
                }
            }
        }
        result = derive_role_provider(raw)
        assert result == ("openai", "CUSTOM_KEY")

    def test_returns_none_no_provider(self):
        """Returns None when provider is missing."""
        from initrunner.services.doctor import derive_role_provider

        raw = {"spec": {"model": {"name": "gpt-5-mini"}}}
        assert derive_role_provider(raw) is None

    def test_returns_none_empty_spec(self):
        """Returns None for empty spec."""
        from initrunner.services.doctor import derive_role_provider

        assert derive_role_provider({"spec": {}}) is None


class TestBumpSpecVersion:
    def test_bumps_version(self):
        """bump_spec_version sets metadata.spec_version."""
        from initrunner.services.doctor import bump_spec_version

        data = {"metadata": {"name": "test", "spec_version": 1}, "spec": {}}
        result = bump_spec_version(data, 2)
        assert result["metadata"]["spec_version"] == 2
        # Original unchanged
        assert data["metadata"]["spec_version"] == 1


class TestBumpSpecVersionText:
    def test_replaces_existing(self):
        """Replaces an existing spec_version line."""
        from initrunner.services.doctor import bump_spec_version_text

        text = (
            "apiVersion: initrunner/v1\n"
            "metadata:\n"
            "  name: test\n"
            "  spec_version: 1\n"
            "spec:\n"
            "  role: test\n"
        )
        result = bump_spec_version_text(text, 2)
        assert "  spec_version: 2\n" in result
        assert "spec_version: 1" not in result

    def test_inserts_missing(self):
        """Inserts spec_version when missing from metadata block."""
        from initrunner.services.doctor import bump_spec_version_text

        text = "apiVersion: initrunner/v1\nmetadata:\n  name: test\nspec:\n  role: test\n"
        result = bump_spec_version_text(text, 2)
        assert "  spec_version: 2\n" in result
        # Inserted before spec:
        lines = result.split("\n")
        sv_idx = next(i for i, line in enumerate(lines) if "spec_version:" in line)
        spec_idx = next(i for i, line in enumerate(lines) if line.startswith("spec:"))
        assert sv_idx < spec_idx

    def test_preserves_formatting(self):
        """Comments, block scalars, and flow-style lists survive the bump."""
        from initrunner.services.doctor import bump_spec_version_text

        text = (
            "# Top-level comment\n"
            "apiVersion: initrunner/v1\n"
            "kind: Agent\n"
            "metadata:\n"
            "  name: test\n"
            "  tags: [engineering, review]\n"
            "spec:\n"
            "  role: |\n"
            "    You are a helpful assistant.\n"
            "    Be concise.\n"
            "  model:\n"
            "    provider: openai\n"
        )
        result = bump_spec_version_text(text, 2)
        assert "# Top-level comment" in result
        assert "tags: [engineering, review]" in result
        assert "  role: |" in result
        assert "    You are a helpful assistant." in result

    def test_preserves_four_space_indent(self):
        """Uses the file's own indent style (4 spaces)."""
        from initrunner.services.doctor import bump_spec_version_text

        text = "metadata:\n    name: test\nspec:\n    role: test\n"
        result = bump_spec_version_text(text, 2)
        assert "    spec_version: 2\n" in result

    def test_raises_on_no_metadata(self):
        """Raises ValueError when metadata: block is missing."""
        import pytest

        from initrunner.services.doctor import bump_spec_version_text

        with pytest.raises(ValueError, match="no metadata"):
            bump_spec_version_text("spec:\n  role: test\n", 2)

    def test_preserves_inline_comment(self):
        """Preserves trailing inline comment on spec_version line."""
        from initrunner.services.doctor import bump_spec_version_text

        text = "metadata:\n  name: test\n  spec_version: 1  # keep current\nspec:\n"
        result = bump_spec_version_text(text, 2)
        assert "  spec_version: 2  # keep current\n" in result


# ---------------------------------------------------------------------------
# Text patching: patch_deprecation_text
# ---------------------------------------------------------------------------


class TestPatchStoreBackendZvec:
    def test_replaces_zvec_with_lancedb(self):
        from initrunner.services.doctor import _patch_store_backend_zvec

        text = "spec:\n  ingest:\n    sources:\n      - '*.md'\n    store_backend: zvec\n"
        result = _patch_store_backend_zvec(text, "spec.ingest.store_backend")
        assert "store_backend: lancedb" in result
        assert "store_backend: zvec" not in result

    def test_preserves_inline_comment(self):
        from initrunner.services.doctor import _patch_store_backend_zvec

        text = "spec:\n  memory:\n    store_backend: zvec  # old backend\n"
        result = _patch_store_backend_zvec(text, "spec.memory.store_backend")
        assert "store_backend: lancedb  # old backend" in result

    def test_raises_on_missing_section(self):
        import pytest

        from initrunner.services.doctor import _patch_store_backend_zvec

        text = "spec:\n  model:\n    name: test\n"
        with pytest.raises(ValueError, match="Cannot locate"):
            _patch_store_backend_zvec(text, "spec.ingest.store_backend")


class TestPatchMaxMemoriesToSemantic:
    def test_no_existing_semantic(self):
        from initrunner.services.doctor import _patch_max_memories_to_semantic

        text = "spec:\n  memory:\n    max_memories: 500\n    store_backend: lancedb\n"
        result = _patch_max_memories_to_semantic(text)
        assert "max_memories: 500" in result
        assert "semantic:" in result
        # The max_memories should be indented under semantic
        lines = result.split("\n")
        sem_idx = next(i for i, l in enumerate(lines) if "semantic:" in l)
        mm_idx = next(i for i, l in enumerate(lines) if "max_memories: 500" in l)
        assert mm_idx == sem_idx + 1

    def test_existing_semantic_without_max_memories(self):
        from initrunner.services.doctor import _patch_max_memories_to_semantic

        text = (
            "spec:\n"
            "  memory:\n"
            "    max_memories: 500\n"
            "    semantic:\n"
            "      embedding_model: text-embedding-3-small\n"
        )
        result = _patch_max_memories_to_semantic(text)
        # max_memories should be removed from top level and added under semantic
        lines = result.split("\n")
        # No top-level max_memories as direct child of memory
        memory_children = [
            l for l in lines if l.startswith("    ") and not l.startswith("      ") and l.strip()
        ]
        assert not any("max_memories" in c for c in memory_children)
        # max_memories exists under semantic
        assert any("      max_memories: 500" in l for l in lines)

    def test_existing_semantic_with_max_memories(self):
        from initrunner.services.doctor import _patch_max_memories_to_semantic

        text = "spec:\n  memory:\n    max_memories: 500\n    semantic:\n      max_memories: 200\n"
        result = _patch_max_memories_to_semantic(text)
        # Top-level max_memories removed; existing nested 200 takes precedence
        lines = [l for l in result.split("\n") if "max_memories" in l]
        assert len(lines) == 1
        assert "200" in lines[0]

    def test_preserves_trailing_comment(self):
        from initrunner.services.doctor import _patch_max_memories_to_semantic

        text = "spec:\n  memory:\n    max_memories: 500  # important\n"
        result = _patch_max_memories_to_semantic(text)
        assert "max_memories: 500  # important" in result

    def test_raises_on_missing_memory(self):
        import pytest

        from initrunner.services.doctor import _patch_max_memories_to_semantic

        text = "spec:\n  model:\n    name: test\n"
        with pytest.raises(ValueError, match="Cannot locate memory"):
            _patch_max_memories_to_semantic(text)


# ---------------------------------------------------------------------------
# CLI: --fix integration tests
# ---------------------------------------------------------------------------

# Common patches to suppress ollama/dotenv side effects in fix tests
_PATCH_DOTENV = patch("initrunner.agent.loader._load_dotenv")
_PATCH_OLLAMA = patch("urllib.request.urlopen", side_effect=Exception("no ollama"))


def _clear_provider_keys(monkeypatch):
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "CO_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


class TestDoctorFixSDK:
    def test_fix_installs_missing_sdk(self, monkeypatch):
        """--fix --yes with key set but SDK missing installs the extra."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        _clear_provider_keys(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        mock_diag = MagicMock()
        mock_diag.provider = "anthropic"
        mock_diag.env_var = "ANTHROPIC_API_KEY"
        mock_diag.fixable_sdk = True
        mock_diag.fixable_key = False
        mock_diag.extras_name = "anthropic"

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[mock_diag]):
                with patch("initrunner.cli._helpers.install_extra", return_value=True) as m:
                    result = runner.invoke(app, ["doctor", "--fix", "--yes"])

        assert result.exit_code == 0
        m.assert_called_once_with("anthropic")
        assert "Installed" in result.output

    def test_fix_no_action_when_sdk_present(self, monkeypatch):
        """--fix with key+SDK both set does nothing extra."""
        _clear_provider_keys(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_diag = MagicMock()
        mock_diag.provider = "openai"
        mock_diag.env_var = "OPENAI_API_KEY"
        mock_diag.fixable_sdk = False
        mock_diag.fixable_key = False
        mock_diag.extras_name = None

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[mock_diag]):
                with patch("initrunner.cli._helpers.install_extra") as m:
                    result = runner.invoke(app, ["doctor", "--fix", "--yes"])

        assert result.exit_code == 0
        m.assert_not_called()


class TestDoctorFixAPIKey:
    def test_fix_role_derives_provider(self, monkeypatch, tmp_path):
        """--fix --yes --role prints guidance for the role's provider key."""
        _clear_provider_keys(monkeypatch)

        p = tmp_path / "role.yaml"
        p.write_text(_valid_role_yaml())

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[]):
                with patch("initrunner.cli._helpers.handle_api_key") as mock_hak:
                    result = runner.invoke(app, ["doctor", "--fix", "--yes", "--role", str(p)])

        assert result.exit_code == 0
        # --yes skips interactive key prompt, prints manual guidance
        mock_hak.assert_not_called()
        assert "OPENAI_API_KEY" in result.output

    def test_fix_yes_skips_key_prompt(self, monkeypatch):
        """--fix --yes with key-fixable provider prints guidance (keys need interactive input)."""
        _clear_provider_keys(monkeypatch)

        mock_diag = MagicMock()
        mock_diag.provider = "openai"
        mock_diag.env_var = "OPENAI_API_KEY"
        mock_diag.fixable_sdk = False
        mock_diag.fixable_key = True
        mock_diag.extras_name = None

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[mock_diag]):
                with patch("initrunner.cli._helpers.handle_api_key") as mock_hak:
                    result = runner.invoke(app, ["doctor", "--fix", "--yes"])

        assert result.exit_code == 0
        mock_hak.assert_not_called()
        assert "OPENAI_API_KEY" in result.output

    def test_fix_yes_multiple_skips_key(self, monkeypatch):
        """--fix --yes with multiple key-fixable providers prints guidance, no prompt."""
        _clear_provider_keys(monkeypatch)

        diag1 = MagicMock(
            provider="openai",
            env_var="OPENAI_API_KEY",
            fixable_sdk=False,
            fixable_key=True,
            extras_name=None,
        )
        diag2 = MagicMock(
            provider="anthropic",
            env_var="ANTHROPIC_API_KEY",
            fixable_sdk=False,
            fixable_key=True,
            extras_name="anthropic",
        )

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch(
                "initrunner.services.doctor.diagnose_providers", return_value=[diag1, diag2]
            ):
                with patch("initrunner.cli._helpers.handle_api_key") as mock_hak:
                    result = runner.invoke(app, ["doctor", "--fix", "--yes"])

        assert result.exit_code == 0
        mock_hak.assert_not_called()
        assert "pass --role" in result.output


class TestDoctorFixRole:
    def test_fix_installs_missing_extra(self, monkeypatch, tmp_path):
        """--fix --role installs missing extras."""
        _clear_provider_keys(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        p = tmp_path / "role.yaml"
        p.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-search
              spec_version: 2
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              tools:
                - type: search
            """)
        )

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[]):
                with patch("initrunner.services.doctor._is_module_available", return_value=False):
                    with patch("initrunner.cli._helpers.install_extra", return_value=True) as m:
                        result = runner.invoke(app, ["doctor", "--fix", "--yes", "--role", str(p)])

        assert result.exit_code == 0
        m.assert_called_with("search")
        assert "Installed" in result.output

    def test_fix_bumps_spec_version(self, monkeypatch, tmp_path):
        """--fix --role bumps spec_version preserving comments, block scalars, flow lists."""
        _clear_provider_keys(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        content = textwrap.dedent("""\
            # Role file with formatting to preserve
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-bump
              tags: [engineering, review]
              spec_version: 1
            spec:
              role: |
                You are a helpful assistant.
                Be concise.
              model:
                provider: openai
                name: gpt-5-mini
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[]):
                result = runner.invoke(app, ["doctor", "--fix", "--yes", "--role", str(p)])

        assert result.exit_code == 0
        assert "Bumped spec_version" in result.output

        raw = p.read_text()
        # Parsed value is correct
        import yaml

        updated = yaml.safe_load(raw)
        assert updated["metadata"]["spec_version"] == 2
        # Formatting preserved
        assert "# Role file with formatting to preserve" in raw
        assert "tags: [engineering, review]" in raw
        assert "  role: |" in raw
        assert "    You are a helpful assistant." in raw

    def test_fix_patches_deprecation_hits(self, monkeypatch, tmp_path):
        """--fix --role auto-patches zvec -> lancedb and bumps spec_version."""
        _clear_provider_keys(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        content = textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-zvec
            spec:
              role: test
              model:
                provider: openai
                name: gpt-5-mini
              ingest:
                sources: ["*.md"]
                store_backend: zvec
        """)
        p = tmp_path / "role.yaml"
        p.write_text(content)

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.services.doctor.diagnose_providers", return_value=[]):
                result = runner.invoke(app, ["doctor", "--fix", "--yes", "--role", str(p)])

        patched = p.read_text()
        assert "store_backend: lancedb" in patched
        assert "store_backend: zvec" not in patched
        assert "spec_version: 2" in patched
        assert result.exit_code == 0
        assert "Fixed DEP002" in result.output


class TestDoctorFixNonTTY:
    def test_fix_without_yes_non_tty(self, monkeypatch):
        """--fix without --yes on non-TTY exits 1."""
        _clear_provider_keys(monkeypatch)

        with _PATCH_DOTENV, _PATCH_OLLAMA:
            with patch("initrunner.cli.doctor_cmd.sys") as mock_sys:
                mock_sys.stdin.isatty.return_value = False
                result = runner.invoke(app, ["doctor", "--fix"])

        assert result.exit_code == 1
        assert "--yes" in result.output


# ---------------------------------------------------------------------------
# Security diagnosis
# ---------------------------------------------------------------------------


def _make_role_with_triggers(trigger_types: list[str], preset: str | None = None):
    """Build a minimal RoleDefinition with specified trigger types and optional security preset."""
    from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition
    from initrunner.agent.schema.security import SecurityPolicy

    triggers_raw: list[dict] = []
    for t in trigger_types:
        if t == "webhook":
            triggers_raw.append({"type": "webhook", "path": "/hook"})
        elif t == "cron":
            triggers_raw.append({"type": "cron", "schedule": "0 * * * *", "prompt": "check"})
        elif t == "telegram":
            triggers_raw.append({"type": "telegram"})
        elif t == "discord":
            triggers_raw.append({"type": "discord"})

    security = (
        SecurityPolicy(preset=preset) if preset else SecurityPolicy()  # type: ignore[arg-type]
    )

    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-sec", spec_version=2),
        spec=AgentSpec(
            role="Test",
            model=ModelConfig(provider="openai", name="gpt-4o"),
            triggers=triggers_raw,
            security=security,
        ),
    )


class TestDiagnoseSecurity:
    def test_warns_default_with_webhook(self) -> None:
        from initrunner.services.doctor import diagnose_security

        role = _make_role_with_triggers(["webhook"])
        diag = diagnose_security(role)
        assert diag.warning is not None
        assert "defaults" in diag.warning

    def test_no_warn_with_cron_only(self) -> None:
        from initrunner.services.doctor import diagnose_security

        role = _make_role_with_triggers(["cron"])
        diag = diagnose_security(role)
        assert diag.warning is None

    def test_no_warn_with_preset(self) -> None:
        from initrunner.services.doctor import diagnose_security

        role = _make_role_with_triggers(["webhook"], preset="public")
        diag = diagnose_security(role)
        assert diag.warning is None

    def test_warns_development_with_telegram(self) -> None:
        from initrunner.services.doctor import diagnose_security

        role = _make_role_with_triggers(["telegram"], preset="development")
        diag = diagnose_security(role)
        assert diag.warning is not None
        assert "relaxes" in diag.warning

    def test_policy_dir_detection(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_security

        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "  /some/path  ")
        role = _make_role_with_triggers([])
        diag = diagnose_security(role)
        assert diag.policy_dir_set is True

    def test_policy_dir_empty(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_security

        monkeypatch.delenv("INITRUNNER_POLICY_DIR", raising=False)
        role = _make_role_with_triggers([])
        diag = diagnose_security(role)
        assert diag.policy_dir_set is False

    def test_policy_dir_whitespace_only(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_security

        monkeypatch.setenv("INITRUNNER_POLICY_DIR", "   ")
        role = _make_role_with_triggers([])
        diag = diagnose_security(role)
        assert diag.policy_dir_set is False


# ---------------------------------------------------------------------------
# Extended diagnostics helpers
# ---------------------------------------------------------------------------


def _make_role_with_tools(tools_raw: list[dict], *, skills: list[str] | None = None):
    """Build a minimal RoleDefinition with specified tools."""
    from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-diag", spec_version=2),
        spec=AgentSpec(
            role="Test",
            model=ModelConfig(provider="openai", name="gpt-4o"),
            tools=tools_raw,
            skills=skills or [],
        ),
    )


def _make_role_with_memory(store_path: str | None = None):
    """Build a minimal RoleDefinition with memory configured."""
    from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
    from initrunner.agent.schema.memory import MemoryConfig
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name="test-mem", spec_version=2),
        spec=AgentSpec(
            role="Test",
            model=ModelConfig(provider="openai", name="gpt-4o"),
            memory=MemoryConfig(store_path=store_path),
        ),
    )


# ---------------------------------------------------------------------------
# Extended diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnoseMcpServers:
    def test_no_mcp_tools(self) -> None:
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools([])
        result = diagnose_mcp_servers(role, None)
        assert result == []

    def test_static_mode_skips(self) -> None:
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools([{"type": "mcp", "transport": "stdio", "command": "echo"}])
        result = diagnose_mcp_servers(role, None, deep=False)
        assert len(result) == 1
        assert result[0].status == "skipped"

    def test_deep_deferred_skipped(self) -> None:
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools(
            [{"type": "mcp", "transport": "stdio", "command": "echo", "defer": True}]
        )
        result = diagnose_mcp_servers(role, None, deep=True)
        assert len(result) == 1
        assert result[0].status == "skipped"

    def test_deep_healthy(self) -> None:
        from initrunner.mcp.health import McpServerHealth
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools([{"type": "mcp", "transport": "stdio", "command": "echo"}])
        mock_health = McpServerHealth(
            status="healthy", latency_ms=42, tool_count=3, error=None, checked_at=""
        )
        with patch("initrunner.mcp.health.check_health_sync", return_value=mock_health):
            result = diagnose_mcp_servers(role, None, deep=True)

        assert len(result) == 1
        assert result[0].status == "healthy"
        assert result[0].latency_ms == 42
        assert result[0].tool_count == 3

    def test_deep_unhealthy(self) -> None:
        from initrunner.mcp.health import McpServerHealth
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools([{"type": "mcp", "transport": "stdio", "command": "echo"}])
        mock_health = McpServerHealth(
            status="unhealthy", latency_ms=5000, tool_count=0, error="timeout", checked_at=""
        )
        with patch("initrunner.mcp.health.check_health_sync", return_value=mock_health):
            result = diagnose_mcp_servers(role, None, deep=True)

        assert result[0].status == "unhealthy"
        assert result[0].error == "timeout"

    def test_deep_exception_caught(self) -> None:
        from initrunner.services.doctor import diagnose_mcp_servers

        role = _make_role_with_tools([{"type": "mcp", "transport": "stdio", "command": "echo"}])
        with patch("initrunner.mcp.health.check_health_sync", side_effect=RuntimeError("boom")):
            result = diagnose_mcp_servers(role, None, deep=True)

        assert result[0].status == "unhealthy"
        assert "boom" in result[0].error


class TestDiagnoseSkills:
    def test_resolved_skill(self, tmp_path) -> None:
        from initrunner.agent.schema.role import SkillDefinition, SkillFrontmatter
        from initrunner.agent.skills import ResolvedSkill
        from initrunner.services.doctor import diagnose_skills

        skill_def = SkillDefinition(
            frontmatter=SkillFrontmatter(name="test-skill", description="test"),
            prompt="body",
        )
        resolved = ResolvedSkill(
            definition=skill_def,
            source_path=tmp_path / "SKILL.md",
            requirement_statuses=[],
        )
        with patch("initrunner.agent.skills.resolve_skills", return_value=[resolved]):
            result = diagnose_skills(["test-skill"], tmp_path, None)

        assert len(result) == 1
        assert result[0].resolved is True
        assert result[0].unmet_requirements == []

    def test_unmet_requirements(self, tmp_path) -> None:
        from initrunner.agent.schema.role import SkillDefinition, SkillFrontmatter
        from initrunner.agent.skills import RequirementStatus, ResolvedSkill
        from initrunner.services.doctor import diagnose_skills

        skill_def = SkillDefinition(
            frontmatter=SkillFrontmatter(name="test-skill", description="test"),
            prompt="body",
        )
        resolved = ResolvedSkill(
            definition=skill_def,
            source_path=tmp_path / "SKILL.md",
            requirement_statuses=[
                RequirementStatus(name="FOO_KEY", kind="env", met=False, detail="FOO_KEY not set"),
                RequirementStatus(name="bar", kind="bin", met=True, detail=""),
            ],
        )
        with patch("initrunner.agent.skills.resolve_skills", return_value=[resolved]):
            result = diagnose_skills(["test-skill"], tmp_path, None)

        assert result[0].resolved is True
        assert len(result[0].unmet_requirements) == 1
        assert "FOO_KEY" in result[0].unmet_requirements[0]

    def test_unresolved_skill(self) -> None:
        from initrunner.agent.skills import SkillLoadError
        from initrunner.services.doctor import diagnose_skills

        with patch(
            "initrunner.agent.skills.resolve_skills",
            side_effect=SkillLoadError("not found"),
        ):
            result = diagnose_skills(["missing-skill"], None, None)

        assert len(result) == 1
        assert result[0].resolved is False
        assert "not found" in result[0].error


class TestDiagnoseCustomTools:
    def test_locatable_static(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools([{"type": "custom", "module": "json"}])
        result = diagnose_custom_tools(role, None, deep=False)
        assert len(result) == 1
        assert result[0].locatable is True
        assert result[0].importable is None  # not attempted

    def test_not_locatable(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools([{"type": "custom", "module": "nonexistent_module_xyz_123"}])
        result = diagnose_custom_tools(role, None, deep=False)
        assert result[0].locatable is False
        assert "not found" in result[0].error

    def test_deep_importable(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools([{"type": "custom", "module": "json"}])
        result = diagnose_custom_tools(role, None, deep=True)
        assert result[0].locatable is True
        assert result[0].importable is True

    def test_deep_function_found(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools([{"type": "custom", "module": "json", "function": "dumps"}])
        result = diagnose_custom_tools(role, None, deep=True)
        assert result[0].callable_found is True

    def test_deep_function_missing(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools(
            [{"type": "custom", "module": "json", "function": "nonexistent_func_xyz"}]
        )
        result = diagnose_custom_tools(role, None, deep=True)
        assert result[0].callable_found is False
        assert "not found" in result[0].error

    def test_role_dir_added_to_path(self, tmp_path) -> None:
        """role_dir is added to sys.path during find_spec and cleaned up after."""
        import sys

        from initrunner.services.doctor import diagnose_custom_tools

        # Create a module in tmp_path
        (tmp_path / "my_tool.py").write_text("def hello(): pass\n")

        role = _make_role_with_tools([{"type": "custom", "module": "my_tool"}])
        result = diagnose_custom_tools(role, tmp_path, deep=False)
        assert result[0].locatable is True
        # sys.path should be cleaned up
        assert str(tmp_path) not in sys.path

    def test_no_custom_tools(self) -> None:
        from initrunner.services.doctor import diagnose_custom_tools

        role = _make_role_with_tools([{"type": "datetime"}])
        result = diagnose_custom_tools(role, None)
        assert result == []


class TestDiagnoseMemoryStore:
    def test_no_memory_returns_none(self) -> None:
        from initrunner.services.doctor import diagnose_memory_store

        role = _make_role_with_tools([])
        result = diagnose_memory_store(role)
        assert result is None

    def test_parent_writable(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_memory_store

        role = _make_role_with_memory(str(tmp_path / "test.lance"))
        result = diagnose_memory_store(role)
        assert result is not None
        assert result.parent_exists is True
        assert result.parent_writable is True
        assert result.db_opens is None  # static mode

    def test_parent_missing(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_memory_store

        role = _make_role_with_memory(str(tmp_path / "nonexistent" / "test.lance"))
        result = diagnose_memory_store(role)
        assert result is not None
        assert result.parent_exists is False

    def test_deep_db_opens(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_memory_store

        role = _make_role_with_memory(str(tmp_path / "test.lance"))
        # Create the store path so deep mode attempts open
        (tmp_path / "test.lance").mkdir()

        mock_store = MagicMock()
        with patch("initrunner.stores.factory.create_memory_store", return_value=mock_store):
            result = diagnose_memory_store(role, deep=True)

        assert result.db_opens is True
        mock_store.close.assert_called_once()

    def test_deep_db_open_fails(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_memory_store

        role = _make_role_with_memory(str(tmp_path / "test.lance"))
        (tmp_path / "test.lance").mkdir()

        with patch(
            "initrunner.stores.factory.create_memory_store",
            side_effect=RuntimeError("corrupt"),
        ):
            result = diagnose_memory_store(role, deep=True)

        assert result.db_opens is False
        assert "corrupt" in result.error


class TestDiagnoseTriggers:
    def test_cron_valid(self) -> None:
        from initrunner.services.doctor import diagnose_triggers

        role = _make_role_with_triggers(["cron"])
        result = diagnose_triggers(role)
        assert len(result) == 1
        assert result[0].trigger_type == "cron"
        assert result[0].issues == []

    def test_telegram_token_missing(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_triggers

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        role = _make_role_with_triggers(["telegram"])
        result = diagnose_triggers(role)
        assert len(result) == 1
        assert any("TELEGRAM_BOT_TOKEN" in issue for issue in result[0].issues)

    def test_telegram_token_set(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_triggers

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-123")
        role = _make_role_with_triggers(["telegram"])
        result = diagnose_triggers(role)
        assert result[0].issues == []

    def test_discord_token_missing(self, monkeypatch) -> None:
        from initrunner.services.doctor import diagnose_triggers

        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        role = _make_role_with_triggers(["discord"])
        result = diagnose_triggers(role)
        assert any("DISCORD_BOT_TOKEN" in issue for issue in result[0].issues)

    def test_file_watch_paths_missing(self, tmp_path) -> None:
        from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.services.doctor import diagnose_triggers

        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test-fw", spec_version=2),
            spec=AgentSpec(
                role="Test",
                model=ModelConfig(provider="openai", name="gpt-4o"),
                triggers=[{"type": "file_watch", "paths": [str(tmp_path / "nope")]}],
            ),
        )
        result = diagnose_triggers(role)
        assert any("does not exist" in issue for issue in result[0].issues)

    def test_file_watch_paths_exist(self, tmp_path) -> None:
        from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
        from initrunner.agent.schema.role import AgentSpec, RoleDefinition
        from initrunner.services.doctor import diagnose_triggers

        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        role = RoleDefinition(
            apiVersion=ApiVersion.V1,
            kind=Kind.AGENT,
            metadata=RoleMetadata(name="test-fw", spec_version=2),
            spec=AgentSpec(
                role="Test",
                model=ModelConfig(provider="openai", name="gpt-4o"),
                triggers=[{"type": "file_watch", "paths": [str(watch_dir)]}],
            ),
        )
        result = diagnose_triggers(role)
        assert result[0].issues == []

    def test_webhook_valid_port(self) -> None:
        from initrunner.services.doctor import diagnose_triggers

        role = _make_role_with_triggers(["webhook"])
        result = diagnose_triggers(role)
        # Default port 8080 is valid
        assert result[0].issues == []


class TestDiagnoseFlow:
    def test_valid_flow(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_flow

        # Create a minimal role file
        role_yaml = tmp_path / "role.yaml"
        role_yaml.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Agent
            metadata:
              name: test-agent
              spec_version: 2
            spec:
              role: Test
              model:
                provider: openai
                name: gpt-4o
            """)
        )
        flow_yaml = tmp_path / "flow.yaml"
        flow_yaml.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Flow
            metadata:
              name: test-flow
            spec:
              agents:
                agent-a:
                  role: role.yaml
            """)
        )
        diag = diagnose_flow(flow_yaml)
        assert diag.flow_valid is True
        assert "agent-a" in diag.agent_diagnostics

    def test_flow_missing_role(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_flow

        flow_yaml = tmp_path / "flow.yaml"
        flow_yaml.write_text(
            textwrap.dedent("""\
            apiVersion: initrunner/v1
            kind: Flow
            metadata:
              name: test-flow
            spec:
              agents:
                agent-a:
                  role: nonexistent.yaml
            """)
        )
        diag = diagnose_flow(flow_yaml)
        assert diag.flow_valid is False
        assert "agent-a" in diag.missing_roles

    def test_flow_parse_error(self, tmp_path) -> None:
        from initrunner.services.doctor import diagnose_flow

        flow_yaml = tmp_path / "flow.yaml"
        flow_yaml.write_text("not: valid: yaml: [")
        diag = diagnose_flow(flow_yaml)
        assert diag.flow_valid is False


class TestDiagnoseRoleDeep:
    def test_aggregates_all_checks(self) -> None:
        from initrunner.services.doctor import diagnose_role_deep

        role = _make_role_with_triggers(["cron"])
        diag = diagnose_role_deep(role, None)
        assert isinstance(diag.mcp_servers, list)
        assert isinstance(diag.skills, list)
        assert isinstance(diag.custom_tools, list)
        assert isinstance(diag.triggers, list)
        assert len(diag.triggers) == 1


class TestRoleDiagnosticsToChecks:
    def test_conversion(self) -> None:
        from initrunner.services.doctor import (
            McpDiagnosis,
            MemoryStoreDiagnosis,
            RoleDiagnostics,
            SkillDiagnosis,
            TriggerDiagnosis,
            role_diagnostics_to_checks,
        )

        diag = RoleDiagnostics(
            mcp_servers=[
                McpDiagnosis("test-mcp", "healthy", 42, 3, None),
            ],
            skills=[
                SkillDiagnosis("my-skill", True, "/path", [], None),
            ],
            custom_tools=[],
            memory_store=MemoryStoreDiagnosis("/store", True, True, None, None),
            triggers=[
                TriggerDiagnosis("cron", "cron: 0 * * * *", []),
            ],
        )
        checks = role_diagnostics_to_checks(diag)
        assert len(checks) == 4
        assert checks[0]["status"] == "ok"
        assert checks[0]["name"] == "mcp: test-mcp"


# ---------------------------------------------------------------------------
# CLI flag interaction tests
# ---------------------------------------------------------------------------


class TestDoctorFlagInteractions:
    def test_role_and_flow_mutually_exclusive(self, tmp_path) -> None:
        role = tmp_path / "role.yaml"
        role.touch()
        flow = tmp_path / "flow.yaml"
        flow.touch()

        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--role", str(role), "--flow", str(flow)])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_deep_requires_role_or_flow(self) -> None:
        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--deep"])
        assert result.exit_code == 1
        assert "--deep requires" in result.output

    def test_flow_and_quickstart_mutually_exclusive(self, tmp_path) -> None:
        flow = tmp_path / "flow.yaml"
        flow.touch()
        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--flow", str(flow), "--quickstart"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_flow_and_fix_mutually_exclusive(self, tmp_path) -> None:
        flow = tmp_path / "flow.yaml"
        flow.touch()
        with patch("initrunner.agent.loader._load_dotenv"):
            with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
                result = runner.invoke(app, ["doctor", "--flow", str(flow), "--fix", "--yes"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output
