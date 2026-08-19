from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.models.schemas import (
    ResetSandboxResponse,
    SandboxFileResponse,
    SandboxFileUpdate,
    SandboxRouteResponse,
    SandboxResponse,
)
from app.services.sandbox_manager import SandboxManager
from app.services.sandbox_client import HTTPError, ResponseSpec

LOCAL_DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = list(LOCAL_DEV_ORIGINS)
    for candidate in configured.split(","):
        origin = candidate.strip()
        if origin and origin not in origins:
            origins.append(origin)
    return origins

manager: SandboxManager | None = None


def _get_manager() -> SandboxManager:
    global manager
    if manager is None:
        manager = SandboxManager()
    return manager


app = FastAPI(
    title="Spinbox API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def reconcile_warm_runner_pool() -> None:
    """Refill the warm runner pool without blocking request readiness."""
    _get_manager()._schedule_reconcile_warm_pool()


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    """Expose a lightweight health endpoint for local development checks."""
    return {"status": "ok"}


@app.post("/sandboxes", response_model=SandboxResponse)
async def create_sandbox() -> dict[str, Any]:
    """Create a sandbox and return its initial metadata."""
    sandbox_manager = _get_manager()
    sandbox = await sandbox_manager.create_sandbox()
    return await sandbox_manager.get_summary(sandbox.id)


@app.get("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(sandbox_id: str) -> dict[str, Any]:
    """Return metadata for a specific sandbox."""
    return await _get_manager().get_summary(sandbox_id)


@app.delete("/sandboxes/{sandbox_id}", status_code=204)
async def delete_sandbox(sandbox_id: str) -> Response:
    """Delete a sandbox immediately."""
    await _get_manager().delete_sandbox(sandbox_id)
    return Response(status_code=204)


@app.post("/sandboxes/{sandbox_id}/reset", response_model=ResetSandboxResponse)
async def reset_sandbox(sandbox_id: str) -> dict[str, str]:
    """Reset the sandbox file, data, and TTL to their defaults."""
    return await _get_manager().reset_sandbox(sandbox_id)


@app.get("/sandbox/{sandbox_id}/file", response_model=SandboxFileResponse)
async def get_sandbox_file(sandbox_id: str) -> dict[str, Any]:
    """Fetch the current editable `routes.py` contents for a sandbox."""
    return await _get_manager().get_file(sandbox_id)


@app.put("/sandbox/{sandbox_id}/file", response_model=SandboxFileResponse)
async def update_sandbox_file(sandbox_id: str, payload: SandboxFileUpdate) -> dict[str, Any]:
    """Persist and apply an updated `routes.py` file for a sandbox."""
    return await _get_manager().update_file(sandbox_id, payload.content)


@app.post("/sandbox/{sandbox_id}/validate", status_code=204)
async def validate_sandbox_file(sandbox_id: str, payload: SandboxFileUpdate) -> Response:
    """Validate `routes.py` without persisting it to the sandbox."""
    await _get_manager().validate_file(sandbox_id, payload.content)
    return Response(status_code=204)


@app.get("/sandbox/{sandbox_id}/routes", response_model=list[SandboxRouteResponse])
async def get_sandbox_routes(sandbox_id: str) -> list[dict[str, Any]]:
    """Return tester-visible route metadata for a specific sandbox."""
    return await _get_manager().get_routes(sandbox_id)


@app.post("/internal/cleanup")
async def cleanup_expired_sandboxes(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Delete expired sandboxes for Cloud Scheduler or local development."""
    _authorize_internal_request(request, authorization)
    return await _get_manager().cleanup_expired()


@app.api_route("/sandbox/{sandbox_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_root(sandbox_id: str, request: Request) -> Response:
    """Handle proxied requests sent to the sandbox root path."""
    return await _handle_proxy(sandbox_id, "", request)


@app.api_route(
    "/sandbox/{sandbox_id}/{proxy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_sandbox_request(sandbox_id: str, proxy_path: str, request: Request) -> Response:
    """Handle proxied requests sent to nested sandbox routes."""
    return await _handle_proxy(sandbox_id, proxy_path, request)


async def _handle_proxy(sandbox_id: str, proxy_path: str, request: Request) -> Response:
    """Translate an incoming FastAPI request into sandbox runtime execution."""
    body_bytes = await request.body()
    raw_body = body_bytes.decode("utf-8") if body_bytes else None

    try:
        result = await _get_manager().proxy_request(
            sandbox_id,
            method=request.method,
            path=proxy_path,
            query_params=dict(request.query_params),
            headers=dict(request.headers),
            raw_body=raw_body,
        )
    except HTTPError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return _to_fastapi_response(result)


def _to_fastapi_response(result: ResponseSpec) -> Response:
    """Convert the sandbox runtime response shape into a concrete FastAPI response."""
    body = result.body
    headers = result.headers or {}
    if isinstance(body, (dict, list, int, float, bool)) or body is None:
        return JSONResponse(status_code=result.status_code, content=body, headers=headers)
    if isinstance(body, str):
        content_type = headers.get("content-type", "")
        if content_type.lower() == "application/json":
            return Response(status_code=result.status_code, content=body, media_type="application/json", headers=headers)
        return PlainTextResponse(status_code=result.status_code, content=body, headers=headers)
    if isinstance(body, bytes):
        return Response(status_code=result.status_code, content=body, headers=headers)
    return JSONResponse(
        status_code=result.status_code,
        content={"error": "Unsupported response type", "detail": str(type(body))},
        headers=headers,
    )


def _authorize_internal_request(request: Request, authorization: str | None) -> None:
    token = os.getenv("INTERNAL_API_TOKEN")
    if token:
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return

    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Cleanup is only open locally when INTERNAL_API_TOKEN is unset.")
