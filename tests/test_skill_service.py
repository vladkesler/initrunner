"""Tests for initrunner.services.skill_service."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """Create a skill directory with directory-form and flat-form skills."""
    skills = tmp_path / "skills"
    skills.mkdir()

    # Directory-form skill
    web = skills / "web-researcher"
    web.mkdir()
    (web / "SKILL.md").write_text(
        "---\n"
        "name: web-researcher\n"
        "description: Fetch and summarize web pages\n"
        "tools:\n"
        "  - type: web_reader\n"
        "requires:\n"
        "  env: []\n"
        "  bins: []\n"
        "---\n\n"
        "You can fetch web pages.\n"
    )

    # Directory-form with resources
    kube = skills / "kube-tools"
    kube.mkdir()
    (kube / "SKILL.md").write_text(
        "---\n"
        "name: kube-tools\n"
        "description: Kubernetes tools\n"
        "tools:\n"
        "  - type: shell\n"
        "    allowed_commands: [kubectl]\n"
        "requires:\n"
        "  bins: [kubectl]\n"
        "---\n\n"
        "Use kubectl for cluster ops.\n"
    )
    (kube / "scripts").mkdir()
    (kube / "scripts" / "setup.sh").write_text("#!/bin/bash\necho setup")

    # Flat-form skill
    (skills / "code-tools.md").write_text(
        "---\n"
        "name: code-tools\n"
        "description: Code analysis methodology\n"
        "---\n\n"
        "Follow these code review guidelines.\n"
    )

    # Broken skill (malformed frontmatter -- name is not a string)
    broken = skills / "broken-skill"
    broken.mkdir()
    (broken / "SKILL.md").write_text(
        "---\n"
        "name: [not, a, string]\n"
        "description: A broken skill\n"
        "---\n\n"
        "Some body.\n"
    )

    return tmp_path


class TestDiscoverSkillsFull:
    def test_discovers_directory_and_flat_skills(self, skill_dir: Path):
        from initrunner.services.skill_service import discover_skills_full

        results = discover_skills_full([skill_dir])
        names = {s.name for s in results}
        assert "web-researcher" in names
        assert "code-tools" in names

    def test_broken_skills_have_error(self, skill_dir: Path):
        from initrunner.services.skill_service import discover_skills_full

        results = discover_skills_full([skill_dir])
        # broken-skill has malformed name field so it can't parse
        broken = [s for s in results if "broken-skill" in str(s.path)]
        assert len(broken) == 1
        assert broken[0].error is not None

    def test_directory_form_detected(self, skill_dir: Path):
        from initrunner.services.skill_service import discover_skills_full

        results = discover_skills_full([skill_dir])
        web = [s for s in results if s.name == "web-researcher"][0]
        code = [s for s in results if s.name == "code-tools"][0]
        assert web.is_directory_form is True
        assert code.is_directory_form is False

    def test_has_resources_detected(self, skill_dir: Path):
        from initrunner.services.skill_service import discover_skills_full

        results = discover_skills_full([skill_dir])
        kube = [s for s in results if s.name == "kube-tools"][0]
        web = [s for s in results if s.name == "web-researcher"][0]
        assert kube.has_resources is True
        assert web.has_resources is False

    def test_no_name_dedup(self, skill_dir: Path):
        """Duplicate names across scopes should both be listed."""
        from initrunner.services.skill_service import discover_skills_full

        # Add another web-researcher in a separate role dir's skills/ subdirectory
        # (search paths are <role_dir>/skills/, so extra must be a role dir)
        extra = skill_dir / "extra-project"
        extra.mkdir()
        extra_skills = extra / "skills"
        extra_skills.mkdir()
        wr2 = extra_skills / "web-researcher"
        wr2.mkdir()
        (wr2 / "SKILL.md").write_text(
            "---\n"
            "name: web-researcher\n"
            "description: Alternate web researcher\n"
            "---\n\n"
            "Alternate implementation.\n"
        )

        results = discover_skills_full([skill_dir, extra])
        web_skills = [s for s in results if s.name == "web-researcher"]
        assert len(web_skills) == 2  # both listed, not deduplicated

    def test_path_dedup(self, skill_dir: Path):
        """Same resolved path from multiple role_dirs should only appear once."""
        from initrunner.services.skill_service import discover_skills_full

        results = discover_skills_full([skill_dir, skill_dir])
        web_skills = [s for s in results if s.name == "web-researcher"]
        assert len(web_skills) == 1


class TestValidateSkillContent:
    def test_valid_content(self):
        from initrunner.services.skill_service import validate_skill_content

        content = (
            "---\n"
            "name: test-skill\n"
            "description: A test skill\n"
            "---\n\n"
            "Some instructions.\n"
        )
        issues = validate_skill_content(content)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_invalid_frontmatter(self):
        from initrunner.services.skill_service import validate_skill_content

        content = "---\nname: 123\n---\n\nBody.\n"
        issues = validate_skill_content(content)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) > 0

    def test_missing_delimiters(self):
        from initrunner.services.skill_service import validate_skill_content

        content = "no frontmatter here"
        issues = validate_skill_content(content)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) > 0


class TestSaveSkillContent:
    def test_valid_saves(self, tmp_path: Path):
        from initrunner.services.skill_service import save_skill_content

        path = tmp_path / "test.md"
        path.write_text("")
        content = "---\nname: test\ndescription: Test\n---\n\nBody.\n"
        valid, issues = save_skill_content(path, content)
        assert valid is True
        assert path.read_text() == content

    def test_invalid_does_not_save(self, tmp_path: Path):
        from initrunner.services.skill_service import save_skill_content

        path = tmp_path / "test.md"
        original = "original content"
        path.write_text(original)
        content = "no frontmatter"
        valid, issues = save_skill_content(path, content)
        assert valid is False
        assert len(issues) > 0
        assert path.read_text() == original  # not overwritten


class TestDeleteSkill:
    def test_delete_flat(self, tmp_path: Path):
        from initrunner.services.skill_service import delete_skill

        flat = tmp_path / "test.md"
        flat.write_text("---\nname: test\ndescription: T\n---\n")
        delete_skill(flat)
        assert not flat.exists()

    def test_delete_directory_no_resources(self, tmp_path: Path):
        from initrunner.services.skill_service import delete_skill

        d = tmp_path / "my-skill"
        d.mkdir()
        f = d / "SKILL.md"
        f.write_text("---\nname: my-skill\ndescription: T\n---\n")
        delete_skill(f)
        assert not f.exists()
        assert not d.exists()

    def test_delete_blocked_by_resources(self, skill_dir: Path):
        from initrunner.services.skill_service import SkillDeleteBlockedError, delete_skill

        kube_skill = skill_dir / "skills" / "kube-tools" / "SKILL.md"
        with pytest.raises(SkillDeleteBlockedError) as exc_info:
            delete_skill(kube_skill)
        assert len(exc_info.value.resource_files) > 0


class TestCreateSkill:
    def test_creates_directory_form(self, tmp_path: Path):
        from initrunner.services.skill_service import create_skill

        path = create_skill("new-skill", tmp_path)
        assert path.exists()
        assert path.name == "SKILL.md"
        assert "new-skill" in path.read_text()

    def test_rejects_existing_dir(self, tmp_path: Path):
        from initrunner.agent.skills import SkillLoadError
        from initrunner.services.skill_service import create_skill

        (tmp_path / "existing").mkdir()
        with pytest.raises(SkillLoadError):
            create_skill("existing", tmp_path)


class TestResolveAgentSkillRefs:
    def test_resolves_bare_name(self, skill_dir: Path):
        from initrunner.services.skill_service import resolve_agent_skill_refs

        paths = resolve_agent_skill_refs(["web-researcher"], skill_dir, None)
        assert len(paths) == 1
        assert "web-researcher" in str(paths[0])

    def test_resolves_flat_name(self, skill_dir: Path):
        from initrunner.services.skill_service import resolve_agent_skill_refs

        paths = resolve_agent_skill_refs(["code-tools"], skill_dir, None)
        assert len(paths) == 1

    def test_skips_unresolvable(self, skill_dir: Path):
        from initrunner.services.skill_service import resolve_agent_skill_refs

        paths = resolve_agent_skill_refs(["nonexistent-skill"], skill_dir, None)
        assert len(paths) == 0
