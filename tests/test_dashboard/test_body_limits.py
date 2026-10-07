"""Dashboard limits apply before FastAPI's JSON, form and multipart parsers."""

from io import BytesIO
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException, UploadFile

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings


@pytest.mark.asyncio
async def test_public_login_is_capped_and_valid_login_still_works():
    app = create_app(DashboardSettings(api_key="test-key", max_request_body_bytes=64))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:

        async def chunks():
            yield b"api_key=" + b"x" * 40
            yield b"x" * 40

        response = await client.post(
            "/login",
            content=chunks(),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "Request body too large"
        assert "set-cookie" not in response.headers
        valid = await client.post("/login", data={"api_key": "test-key"})
        assert valid.status_code == 303
        assert "initrunner_token=" in valid.headers["set-cookie"]
        assert (await client.get("/api/health")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams"])
async def test_upload_limit_is_separate_and_finite(kind, monkeypatch):
    app = create_app(DashboardSettings(max_request_body_bytes=64, max_upload_body_bytes=1024))
    # Unknown identifiers must reach the router (404), proving the ordinary
    # 64-byte ceiling did not reject this bounded multipart request.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        path = f"/api/{kind}/missing/ingest/upload"
        assert (await client.post(path, files={"files": ("ok.txt", b"x" * 100)})).status_code == 404
        assert (
            await client.post(path, files={"files": ("big.txt", b"x" * 1024)})
        ).status_code == 413
        rejected = await client.post(
            "/api/agents",
            content=b"x" * 65,
            headers={"origin": "http://localhost:5173"},
        )
        assert rejected.status_code == 413
        assert rejected.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.asyncio
async def test_team_per_file_limit_removes_partial_upload_without_ingesting(tmp_path, monkeypatch):
    from initrunner.dashboard.routers import team_ingest
    from tests.conftest import make_role

    role = make_role()
    role.spec.security.resources.max_file_size_mb = 1 / 1024
    team = MagicMock()
    monkeypatch.setattr(team_ingest, "_resolve_team", lambda *args: (team, role))
    monkeypatch.setattr("initrunner.ingestion.manifest.uploads_dir", lambda name: tmp_path)
    ingest = MagicMock()
    monkeypatch.setattr("initrunner.services.ingestion.run_ingest_managed_sync", ingest)
    with pytest.raises(HTTPException) as error:
        await team_ingest.upload_files(
            "team", MagicMock(), [UploadFile(BytesIO(b"x" * 1025), filename="big.txt")]
        )
    assert error.value.status_code == 413
    assert not (tmp_path / "big.txt").exists()
    ingest.assert_not_called()


@pytest.mark.parametrize("setting", ["max_request_body_bytes", "max_upload_body_bytes"])
def test_dashboard_rejects_nonpositive_limits(setting):
    with pytest.raises(ValueError):
        DashboardSettings(**{setting: 0})
