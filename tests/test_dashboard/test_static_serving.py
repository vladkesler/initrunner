"""Tests for static file serving and SPA fallback."""

from unittest.mock import patch

from starlette.testclient import TestClient

from initrunner.dashboard.app import create_app
from initrunner.dashboard.config import DashboardSettings


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_api_404_does_not_fallback(client):
    """API paths should return 404, not the SPA index.html."""
    resp = client.get("/api/nonexistent")
    assert resp.status_code in (404, 405)


def test_static_serving_with_directory(tmp_path):
    """When _static/ exists, static files are served."""
    static_dir = tmp_path / "_static"
    static_dir.mkdir()
    index = static_dir / "index.html"
    index.write_text("<html><body>dashboard</body></html>")

    settings = DashboardSettings()

    with patch("initrunner.dashboard.app._STATIC_DIR", static_dir):
        app = create_app(settings)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dashboard" in resp.text


def test_spa_fallback(tmp_path):
    """Non-API, non-static paths should return index.html (SPA routing)."""
    static_dir = tmp_path / "_static"
    static_dir.mkdir()
    index = static_dir / "index.html"
    index.write_text("<html>spa</html>")

    settings = DashboardSettings()

    with patch("initrunner.dashboard.app._STATIC_DIR", static_dir):
        app = create_app(settings)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/agents/some-id")
    assert resp.status_code == 200
    assert "spa" in resp.text
