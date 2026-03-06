"""Tests for bundle creation and extraction."""

import json
import tarfile
import textwrap

import pytest

from initrunner.packaging.bundle import (
    BundleFile,
    BundleManifest,
    collect_bundle_files,
    create_bundle,
    extract_bundle,
    validate_bundle,
)

MINIMAL_ROLE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: test-agent
      description: A test agent
      author: tester
      version: "1.0.0"
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")

ROLE_WITH_SKILLS_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: skill-agent
      description: Agent with skills
      version: "2.0.0"
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
      skills:
        - web-researcher
""")

ROLE_WITH_BUNDLE_INCLUDE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: bundle-agent
      description: Agent with bundle includes
      version: "1.0.0"
      bundle:
        include:
          - data/*.csv
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
""")

ROLE_WITH_SCHEMA_FILE_YAML = textwrap.dedent("""\
    apiVersion: initrunner/v1
    kind: Agent
    metadata:
      name: schema-agent
      version: "1.0.0"
    spec:
      role: You are helpful.
      model:
        provider: openai
        name: gpt-5-mini
      output:
        type: json_schema
        schema_file: schema.json
""")

SKILL_MD = textwrap.dedent("""\
    ---
    name: web-researcher
    description: Web research skill
    tools:
      - type: http
    ---
    You can research the web.
""")


class TestBundleManifest:
    def test_defaults(self):
        m = BundleManifest(name="test", version="1.0.0")
        assert m.format_version == "1"
        assert m.files == []
        assert m.dependencies == []

    def test_roundtrip_json(self):
        m = BundleManifest(
            name="test",
            version="1.0.0",
            description="A test",
            files=[BundleFile(path="role.yaml", sha256="abc", size=100, kind="role")],
        )
        data = m.model_dump_json()
        m2 = BundleManifest.model_validate_json(data)
        assert m2.name == "test"
        assert len(m2.files) == 1
        assert m2.files[0].kind == "role"


class TestCollectBundleFiles:
    def test_minimal_role(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        files = collect_bundle_files(role_file)
        assert len(files) == 1
        assert files[0][1].path == "role.yaml"
        assert files[0][1].kind == "role"

    def test_role_with_skills(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(ROLE_WITH_SKILLS_YAML)

        # Create skill directory
        skill_dir = tmp_path / "skills" / "web-researcher"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(SKILL_MD)

        files = collect_bundle_files(role_file)
        assert len(files) == 2
        paths = [f[1].path for f in files]
        assert "role.yaml" in paths
        kinds = {f[1].kind for f in files}
        assert "skill" in kinds

    def test_role_with_bundle_include(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(ROLE_WITH_BUNDLE_INCLUDE_YAML)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "sample.csv").write_text("a,b,c\n1,2,3")
        (data_dir / "other.txt").write_text("ignored")

        files = collect_bundle_files(role_file)
        paths = [f[1].path for f in files]
        assert "role.yaml" in paths
        assert "data/data/sample.csv" in paths or "data/sample.csv" in [
            p.split("/", 1)[-1] if "/" in p else p for p in paths
        ]
        # .txt should NOT be included
        assert not any("other.txt" in p for p in paths)

    def test_role_with_schema_file(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(ROLE_WITH_SCHEMA_FILE_YAML)

        schema_file = tmp_path / "schema.json"
        schema_file.write_text('{"type": "object"}')

        files = collect_bundle_files(role_file)
        assert len(files) == 2
        kinds = {f[1].kind for f in files}
        assert "data" in kinds

    def test_no_duplicate_files(self, tmp_path):
        """Same file referenced multiple ways should appear once."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        files = collect_bundle_files(role_file)
        paths = [f[1].path for f in files]
        assert len(paths) == len(set(paths))

    def test_nonexistent_skill_skipped(self, tmp_path):
        """Skills that can't be resolved are skipped."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(ROLE_WITH_SKILLS_YAML)

        # No skill directory — should not raise
        files = collect_bundle_files(role_file)
        assert len(files) == 1  # Only role.yaml


class TestCreateBundle:
    def test_create_minimal(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        output_dir = tmp_path / "output"
        archive = create_bundle(role_file, output_dir=output_dir)

        assert archive.exists()
        assert archive.name == "test-agent-1.0.0.tar.gz"

        # Verify contents
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert "manifest.json" in names
            assert "role.yaml" in names

            # Read manifest
            f = tar.extractfile("manifest.json")
            assert f is not None
            manifest = json.loads(f.read())
            assert manifest["name"] == "test-agent"
            assert manifest["version"] == "1.0.0"

    def test_create_default_output_dir(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        archive = create_bundle(role_file)
        assert archive.parent == tmp_path


class TestValidateBundle:
    def test_valid_bundle(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        archive = create_bundle(role_file, output_dir=tmp_path / "out")
        manifest = validate_bundle(archive)

        assert manifest.name == "test-agent"
        assert len(manifest.files) == 1

    def test_corrupted_bundle(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        archive = create_bundle(role_file, output_dir=tmp_path / "out")

        # Corrupt the archive by modifying a file's hash in manifest
        extract_dir = tmp_path / "corrupt"
        extract_dir.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(extract_dir)

        # Modify the role.yaml content
        (extract_dir / "role.yaml").write_text("corrupted content")

        # Re-pack
        corrupt_archive = tmp_path / "corrupt.tar.gz"
        with tarfile.open(corrupt_archive, "w:gz") as tar:
            tar.add(str(extract_dir / "manifest.json"), arcname="manifest.json")
            tar.add(str(extract_dir / "role.yaml"), arcname="role.yaml")

        with pytest.raises(ValueError, match="Integrity check failed"):
            validate_bundle(corrupt_archive)

    def test_unsafe_path_rejected(self, tmp_path):
        """Archives with path traversal should be rejected."""
        import io

        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            data = b'{"format_version": "1", "name": "evil", "version": "1"}'
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

            manifest_data = json.dumps(
                {
                    "format_version": "1",
                    "name": "evil",
                    "version": "1",
                    "files": [],
                }
            ).encode()
            minfo = tarfile.TarInfo(name="manifest.json")
            minfo.size = len(manifest_data)
            tar.addfile(minfo, io.BytesIO(manifest_data))

        with pytest.raises(ValueError, match="Unsafe path"):
            validate_bundle(archive)


class TestExtractBundle:
    def test_roundtrip(self, tmp_path):
        """Create → extract → verify exact file set."""
        role_file = tmp_path / "role.yaml"
        role_file.write_text(MINIMAL_ROLE_YAML)

        archive = create_bundle(role_file, output_dir=tmp_path / "out")

        extract_dir = tmp_path / "extracted"
        manifest = extract_bundle(archive, extract_dir)

        assert manifest.name == "test-agent"
        assert (extract_dir / "role.yaml").exists()
        assert (extract_dir / "manifest.json").exists()
        assert (extract_dir / "role.yaml").read_text() == MINIMAL_ROLE_YAML

    def test_roundtrip_with_skills(self, tmp_path):
        role_file = tmp_path / "role.yaml"
        role_file.write_text(ROLE_WITH_SKILLS_YAML)

        skill_dir = tmp_path / "skills" / "web-researcher"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(SKILL_MD)

        archive = create_bundle(role_file, output_dir=tmp_path / "out")
        extract_dir = tmp_path / "extracted"
        manifest = extract_bundle(archive, extract_dir)

        assert len(manifest.files) == 2
        # Skill file should be extracted
        skill_files = [f for f in manifest.files if f.kind == "skill"]
        assert len(skill_files) == 1
