"""Bundle creation and extraction for OCI distribution."""

from __future__ import annotations

import glob as globmod
import hashlib
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from initrunner import __version__


class BundleFile(BaseModel):
    """A single file entry in the bundle manifest."""

    path: str
    sha256: str
    size: int
    kind: Literal["role", "skill", "data"]


class BundleManifest(BaseModel):
    """Bundle metadata stored as manifest.json inside the archive."""

    format_version: Literal["1"] = "1"
    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = []
    created_at: str = ""
    initrunner_version: str = __version__
    files: list[BundleFile] = []
    dependencies: list[str] = []
    supported_sandbox_backends: list[Literal["bwrap", "docker"]] = []


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_file(
    collected: list[tuple[Path, BundleFile]],
    abs_path: Path,
    archive_path: str,
    kind: Literal["role", "skill", "data"],
    seen: set[str],
) -> None:
    """Add a file to the collection if not already seen."""
    resolved = str(abs_path.resolve())
    if resolved in seen:
        return
    seen.add(resolved)
    collected.append(
        (
            abs_path,
            BundleFile(
                path=archive_path,
                sha256=_file_sha256(abs_path),
                size=abs_path.stat().st_size,
                kind=kind,
            ),
        )
    )


def collect_bundle_files(role_path: Path) -> list[tuple[Path, BundleFile]]:
    """Collect files for bundling based on deterministic rules.

    Includes:
    1. The role file itself
    2. Resolved skills from spec.skills
    3. Schema-referenced data files (output.schema_file, ingest.sources, docker bind_mounts)
    4. Explicit bundle.include globs from metadata
    """
    import yaml

    from initrunner.agent.schema.role import RoleDefinition

    role_path = role_path.resolve()
    role_dir = role_path.parent

    content = role_path.read_text()
    data = yaml.safe_load(content)
    role = RoleDefinition.model_validate(data)

    collected: list[tuple[Path, BundleFile]] = []
    seen: set[str] = set()

    # 1. Role file
    _add_file(collected, role_path, "role.yaml", "role", seen)

    # 2. Resolved skills
    if role.spec.skills:
        from initrunner.agent.skills import _resolve_skill_path

        for skill_ref in role.spec.skills:
            try:
                skill_path = _resolve_skill_path(skill_ref, role_dir, None)
                # Compute archive path: skills/<dir-name>/SKILL.md or skills/<name>.md
                try:
                    rel = skill_path.relative_to(role_dir)
                    archive_skill_path = str(rel)
                except ValueError:
                    archive_skill_path = f"skills/{skill_path.name}"
                _add_file(collected, skill_path, archive_skill_path, "skill", seen)
            except Exception:
                pass  # Skip unresolvable skills

    # 3. Schema-referenced data files
    # 3a. output.schema_file
    if role.spec.output.schema_file:
        schema_path = role_dir / role.spec.output.schema_file
        if schema_path.is_file():
            _add_file(collected, schema_path, f"data/{schema_path.name}", "data", seen)

    # 3b. ingest.sources glob patterns
    if role.spec.ingest and role.spec.ingest.sources:
        for pattern in role.spec.ingest.sources:
            full_pattern = str(role_dir / pattern)
            for match in sorted(globmod.glob(full_pattern, recursive=True)):
                match_path = Path(match)
                if match_path.is_file():
                    try:
                        rel = match_path.relative_to(role_dir)
                        _add_file(collected, match_path, f"data/{rel}", "data", seen)
                    except ValueError:
                        pass

    # 3c. sandbox bind_mounts sources
    if role.spec.security.sandbox.bind_mounts:
        for mount in role.spec.security.sandbox.bind_mounts:
            mount_path = role_dir / mount.source
            if mount_path.is_file():
                try:
                    rel = mount_path.relative_to(role_dir)
                    _add_file(collected, mount_path, f"data/{rel}", "data", seen)
                except ValueError:
                    pass

    # 4. bundle.include globs
    if role.metadata.bundle and role.metadata.bundle.include:
        for pattern in role.metadata.bundle.include:
            full_pattern = str(role_dir / pattern)
            for match in sorted(globmod.glob(full_pattern, recursive=True)):
                match_path = Path(match)
                if match_path.is_file():
                    try:
                        rel = match_path.relative_to(role_dir)
                        _add_file(collected, match_path, f"data/{rel}", "data", seen)
                    except ValueError:
                        pass

    return collected


def create_bundle(role_path: Path, output_dir: Path | None = None) -> Path:
    """Create a .tar.gz bundle from a role file. Returns archive path."""
    import yaml

    from initrunner.agent.schema.role import RoleDefinition

    role_path = role_path.resolve()
    content = role_path.read_text()
    data = yaml.safe_load(content)
    role = RoleDefinition.model_validate(data)

    files = collect_bundle_files(role_path)

    sandbox_backend = role.spec.security.sandbox.backend
    if sandbox_backend == "none":
        sandbox_backends: list[str] = []
    elif sandbox_backend == "auto":
        sandbox_backends = ["bwrap", "docker"]
    elif sandbox_backend in ("bwrap", "docker"):
        sandbox_backends = [sandbox_backend]
    else:
        sandbox_backends = []

    manifest = BundleManifest(
        name=role.metadata.name,
        version=role.metadata.version or "0.0.0",
        description=role.metadata.description,
        author=role.metadata.author,
        tags=list(role.metadata.tags),
        created_at=datetime.now(UTC).isoformat(),
        initrunner_version=__version__,
        files=[bf for _, bf in files],
        dependencies=list(role.metadata.dependencies),
        supported_sandbox_backends=sandbox_backends,  # type: ignore[arg-type]
    )

    dest_dir = output_dir or role_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{role.metadata.name}-{manifest.version}.tar.gz"
    archive_path = dest_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        # Add manifest.json
        manifest_bytes = manifest.model_dump_json(indent=2).encode()
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        # Add collected files
        for abs_path, bf in files:
            tar.add(str(abs_path), arcname=bf.path)

    return archive_path


def validate_bundle(archive_path: Path) -> BundleManifest:
    """Validate a bundle archive (read-only). Returns manifest."""
    with tarfile.open(archive_path, "r:gz") as tar:
        # Safety: reject paths with .. or absolute paths
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise ValueError(f"Unsafe path in archive: {member.name}")

        manifest_member = tar.getmember("manifest.json")
        f = tar.extractfile(manifest_member)
        if f is None:
            raise ValueError("Cannot read manifest.json from archive")
        manifest = BundleManifest.model_validate_json(f.read())

        # Validate SHA-256 for each file
        for bf in manifest.files:
            member = tar.getmember(bf.path)
            ef = tar.extractfile(member)
            if ef is None:
                raise ValueError(f"Cannot read {bf.path} from archive")
            data = ef.read()
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != bf.sha256:
                raise ValueError(
                    f"Integrity check failed for {bf.path}: expected {bf.sha256}, got {actual_sha}"
                )

    return manifest


def extract_bundle(archive_path: Path, target_dir: Path) -> BundleManifest:
    """Extract a bundle, validate integrity, return manifest."""
    manifest = validate_bundle(archive_path)

    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        # Safety filter: only extract expected files
        allowed = {"manifest.json"} | {bf.path for bf in manifest.files}
        members = [m for m in tar.getmembers() if m.name in allowed]

        # Strip the "data/" prefix so extracted paths match the original
        # development layout (e.g. data/knowledge-base/foo.md -> knowledge-base/foo.md).
        # This keeps role.yaml relative paths working after install.
        for m in members:
            if m.name.startswith("data/"):
                m.name = m.name[5:]  # len("data/") == 5

        tar.extractall(target_dir, members=members)

    return manifest
