from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app
from app.services.sandbox_client import ResponseSpec


class StubManager:
    def _schedule_reconcile_warm_pool(self) -> None:
        return None

    async def cleanup_expired(self) -> dict[str, int]:
        return {"deleted": 2, "remaining": 1}

    async def proxy_request(self, sandbox_id: str, **_: object) -> ResponseSpec:
        return ResponseSpec(
            body={"sandbox_id": sandbox_id},
            status_code=200,
            headers={"content-type": "application/json"},
        )


def test_cleanup_requires_bearer_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.main.manager", StubManager())
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret-token")
    client = TestClient(app)

    unauthorized = client.post("/internal/cleanup")
    authorized = client.post("/internal/cleanup", headers={"Authorization": "Bearer secret-token"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {"deleted": 2, "remaining": 1}


def test_proxy_endpoint_returns_manager_response(monkeypatch) -> None:
    monkeypatch.setattr("app.main.manager", StubManager())
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    client = TestClient(app)

    response = client.get("/sandbox/test-sandbox/users")

    assert response.status_code == 200
    assert response.json() == {"sandbox_id": "test-sandbox"}


def test_allowed_origins_include_configured_cloud_run_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://spinbox-frontend-xyz.a.run.app")

    from app.main import _allowed_origins

    origins = _allowed_origins()

    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins
    assert "https://spinbox-frontend-xyz.a.run.app" in origins
