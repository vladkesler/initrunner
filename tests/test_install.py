"""Install-method detection and the command that adds an extra to this install.

The bar these tests defend: never run an installer that would leave the user
with fewer extras than they started with.  ``uv tool install`` and ``pipx
install`` re-resolve the whole environment from the spec they are handed, so
anything the receipt does not describe exactly has to fall through to a printed
command rather than a subprocess.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from initrunner import _install
from initrunner._install import (
    DOCKER,
    EDITABLE,
    PIP,
    PIPX,
    UNKNOWN,
    UV_PIP,
    UV_TOOL,
    UVX,
    consume_reexec_flag,
    current_extras,
    install_command,
    install_method,
    manual_hint,
    was_reexeced,
)


@pytest.fixture
def clean_env(monkeypatch):
    """No container markers, no re-exec flag, nothing inherited from the runner."""
    for var in ("INITRUNNER_IN_DOCKER", _install.REEXEC_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_install, "_in_container", lambda: False)
    monkeypatch.setattr(_install, "_is_editable", lambda: False)
    monkeypatch.setattr(sys, "platform", "linux")
    return monkeypatch


def _prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    return tmp_path


def _receipt(tmp_path, body: str):
    (tmp_path / "uv-receipt.toml").write_text(body, encoding="utf-8")


def _pipx_metadata(tmp_path, package_or_url):
    (tmp_path / "pipx_metadata.json").write_text(
        json.dumps({"main_package": {"package_or_url": package_or_url}}), encoding="utf-8"
    )


UV_RECEIPT = """
[tool]
requirements = [{ name = "initrunner", extras = ["recommended"] }]
python = ">=3.11"
"""


class TestInstallMethod:
    def test_uv_tool_receipt(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        assert install_method() == UV_TOOL

    def test_pipx_metadata(self, clean_env, tmp_path):
        _pipx_metadata(_prefix(clean_env, tmp_path), "initrunner[recommended]")
        assert install_method() == PIPX

    def test_editable_checkout_wins_over_prefix(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        clean_env.setattr(_install, "_is_editable", lambda: True)
        assert install_method() == EDITABLE

    def test_container_wins_over_everything(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        clean_env.setattr(_install, "_in_container", lambda: True)
        assert install_method() == DOCKER

    def test_uvx_cache_environment(self, clean_env, tmp_path):
        cache = tmp_path / "archive-v0" / "abc123"
        cache.mkdir(parents=True)
        _prefix(clean_env, cache)
        assert install_method() == UVX

    def test_uv_on_path_without_receipt(self, clean_env, tmp_path):
        _prefix(clean_env, tmp_path)
        with patch("shutil.which", return_value="/usr/bin/uv"):
            assert install_method() == UV_PIP

    def test_pip_when_no_uv(self, clean_env, tmp_path):
        _prefix(clean_env, tmp_path)
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            assert install_method() == PIP

    def test_unknown_when_no_installer_at_all(self, clean_env, tmp_path):
        """A uv-made venv has no pip; there is nothing safe to run."""
        _prefix(clean_env, tmp_path)
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=None),
        ):
            assert install_method() == UNKNOWN

    def test_never_raises(self, clean_env):
        clean_env.setattr(_install, "_in_container", lambda: 1 / 0)
        assert install_method() == UNKNOWN

    def test_container_marker_env_var(self, monkeypatch):
        monkeypatch.setenv("INITRUNNER_IN_DOCKER", "1")
        assert _install._in_container() is True


class TestUvToolCommand:
    """The receipt is the source of truth for what the environment must keep."""

    def test_union_keeps_existing_extras(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        cmd = install_command(["search"])
        assert cmd == [
            "uv",
            "tool",
            "install",
            "initrunner[recommended,search]",
            "--python",
            ">=3.11",
        ]

    def test_no_force_flag(self, clean_env, tmp_path):
        """--force recreates the environment; uv already replaces it on change."""
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        cmd = install_command(["search"])
        assert cmd is not None and "--force" not in cmd

    def test_existing_pin_is_preserved(self, clean_env, tmp_path):
        _receipt(
            _prefix(clean_env, tmp_path),
            '[tool]\nrequirements = [{ name = "initrunner", extras = ["recommended"],'
            ' specifier = "==2026.8.10" }]\n',
        )
        assert install_command(["search"]) == [
            "uv",
            "tool",
            "install",
            "initrunner[recommended,search]==2026.8.10",
        ]

    def test_no_pin_is_added(self, clean_env, tmp_path):
        """A specifier in the receipt is what `uv tool upgrade` respects."""
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        cmd = install_command(["search"])
        assert cmd is not None and not any("==" in arg for arg in cmd)

    def test_extras_are_sorted_and_deduplicated(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        cmd = install_command(["vector", "search", "recommended"])
        assert cmd is not None and "initrunner[recommended,search,vector]" in cmd

    @pytest.mark.parametrize(
        "requirements",
        [
            pytest.param(
                '[{ name = "initrunner", directory = "/src/initrunner" }]', id="directory"
            ),
            pytest.param('[{ name = "initrunner", git = "https://x/y.git" }]', id="git"),
            pytest.param('[{ name = "initrunner", url = "https://x/y.whl" }]', id="url"),
            pytest.param('[{ name = "initrunner", editable = true }]', id="editable"),
            pytest.param(
                '[{ name = "initrunner", extras = ["recommended"] }, { name = "pip" }]',
                id="with-package",
            ),
            pytest.param(
                '[{ name = "initrunner", marker = "sys_platform == \'linux\'" }]',
                id="unrecognised-key",
            ),
            pytest.param('[{ name = "something-else" }]', id="not-initrunner"),
            pytest.param("[]", id="empty"),
        ],
    )
    def test_unfamiliar_receipts_do_not_auto_install(self, clean_env, tmp_path, requirements):
        _receipt(_prefix(clean_env, tmp_path), f"[tool]\nrequirements = {requirements}\n")
        assert install_command(["search"]) is None

    def test_unreadable_receipt_does_not_auto_install(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), "this is not toml {{{")
        assert install_command(["search"]) is None

    def test_python_pin_omitted_when_receipt_has_none(self, clean_env, tmp_path):
        _receipt(
            _prefix(clean_env, tmp_path),
            '[tool]\nrequirements = [{ name = "initrunner", extras = ["recommended"] }]\n',
        )
        assert install_command(["search"]) == [
            "uv",
            "tool",
            "install",
            "initrunner[recommended,search]",
        ]

    def test_windows_prints_instead_of_running(self, clean_env, tmp_path):
        """uv rewrites the launcher, which cannot be replaced while running."""
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        clean_env.setattr(sys, "platform", "win32")
        assert install_command(["search"]) is None
        assert "uv tool install" in manual_hint(["search"])


class TestOtherMethods:
    def test_uv_pip_targets_the_running_interpreter(self, clean_env, tmp_path):
        """Without --python this resolves ./.venv, which may be a different env."""
        _prefix(clean_env, tmp_path)
        with patch("shutil.which", return_value="/usr/bin/uv"):
            cmd = install_command(["search"])
        assert cmd == ["uv", "pip", "install", "--python", sys.executable, "initrunner[search]"]

    def test_pip_uses_the_running_interpreter(self, clean_env, tmp_path):
        _prefix(clean_env, tmp_path)
        with (
            patch("shutil.which", return_value=None),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            assert install_command(["search"]) == [
                sys.executable,
                "-m",
                "pip",
                "install",
                "initrunner[search]",
            ]

    @pytest.mark.parametrize("method", [PIPX, EDITABLE, DOCKER, UVX, UNKNOWN])
    def test_print_only_methods(self, clean_env, method):
        clean_env.setattr(_install, "install_method", lambda: method)
        assert install_command(["search"]) is None

    def test_no_extras_is_not_a_command(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        assert install_command([]) is None


class TestManualHint:
    def test_pipx_hint_keeps_existing_extras(self, clean_env, tmp_path):
        _pipx_metadata(_prefix(clean_env, tmp_path), "initrunner[recommended]")
        assert manual_hint(["search"]) == "pipx install --force 'initrunner[recommended,search]'"

    def test_pipx_hint_keeps_a_pin(self, clean_env, tmp_path):
        """fullmatch, not a prefix match: a prefix match would drop the pin."""
        _pipx_metadata(_prefix(clean_env, tmp_path), "initrunner[recommended]==2026.8.10")
        assert (
            manual_hint(["search"])
            == "pipx install --force 'initrunner[recommended,search]==2026.8.10'"
        )

    def test_pipx_hint_on_unreadable_metadata_says_so(self, clean_env, tmp_path):
        _pipx_metadata(_prefix(clean_env, tmp_path), "git+https://example.com/initrunner.git")
        hint = manual_hint(["search"])
        assert "initrunner[search]" in hint
        assert "extras you already had" in hint

    def test_editable_hint_is_uv_sync(self, clean_env):
        clean_env.setattr(_install, "install_method", lambda: EDITABLE)
        assert manual_hint(["search", "vector"]) == "uv sync --extra search --extra vector"

    def test_uvx_hint_uses_from(self, clean_env):
        clean_env.setattr(_install, "install_method", lambda: UVX)
        assert manual_hint(["search"]).startswith("uvx --from 'initrunner[search]' initrunner")

    def test_docker_hint_names_the_build_arg(self, clean_env):
        clean_env.setattr(_install, "install_method", lambda: DOCKER)
        assert "--build-arg EXTRAS=search" in manual_hint(["search"])

    def test_unknown_hint_names_the_interpreter(self, clean_env):
        clean_env.setattr(_install, "install_method", lambda: UNKNOWN)
        assert manual_hint(["search"]) == f"{sys.executable} -m pip install 'initrunner[search]'"

    def test_hint_matches_the_command_when_there_is_one(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        assert manual_hint(["search"]) == (
            "uv tool install 'initrunner[recommended,search]' --python '>=3.11'"
        )

    def test_unfamiliar_receipt_hint_mentions_with_packages(self, clean_env, tmp_path):
        _receipt(
            _prefix(clean_env, tmp_path),
            '[tool]\nrequirements = [{ name = "initrunner", extras = ["recommended"] },'
            ' { name = "pip" }]\n',
        )
        hint = manual_hint(["search"])
        assert "uv tool install" in hint
        assert "--with" in hint


class TestCurrentExtras:
    def test_reads_the_uv_receipt(self, clean_env, tmp_path):
        _receipt(_prefix(clean_env, tmp_path), UV_RECEIPT)
        assert current_extras() == {"recommended"}

    def test_reads_pipx_metadata(self, clean_env, tmp_path):
        _pipx_metadata(_prefix(clean_env, tmp_path), "initrunner[search,vector]")
        assert current_extras() == {"search", "vector"}

    def test_empty_when_there_is_no_record(self, clean_env, tmp_path):
        _prefix(clean_env, tmp_path)
        with patch("shutil.which", return_value="/usr/bin/uv"):
            assert current_extras() == set()


class TestReexecGuard:
    def test_flag_is_consumed_and_remembered(self, monkeypatch):
        """Removed from the environment so children never inherit it."""
        monkeypatch.setenv(_install.REEXEC_ENV_VAR, "1")
        monkeypatch.setattr(_install, "_reexeced", False)
        assert consume_reexec_flag() is True
        assert _install.REEXEC_ENV_VAR not in __import__("os").environ
        assert was_reexeced() is True

    def test_absent_flag(self, monkeypatch):
        monkeypatch.delenv(_install.REEXEC_ENV_VAR, raising=False)
        monkeypatch.setattr(_install, "_reexeced", True)
        assert consume_reexec_flag() is False
        assert was_reexeced() is False


class TestRequirementParsing:
    @pytest.mark.parametrize(
        "text,extras,specifier",
        [
            ("initrunner", set(), ""),
            ("initrunner[recommended]", {"recommended"}, ""),
            ("initrunner[a,b]", {"a", "b"}, ""),
            ("initrunner==1.2", set(), "==1.2"),
            ("initrunner[a]>=1.0", {"a"}, ">=1.0"),
        ],
    )
    def test_parses(self, text, extras, specifier):
        assert _install._parse_requirement(text) == (extras, specifier)

    @pytest.mark.parametrize(
        "text",
        [
            "git+https://example.com/initrunner.git",
            "/src/initrunner",
            "other-package[extra]",
            "initrunner-extras",
            "initrunner[a] ; python_version > '3.11'",
        ],
    )
    def test_rejects_anything_else(self, text):
        assert _install._parse_requirement(text) is None
