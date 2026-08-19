from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sandbox_runner.service import MultiTenantSandboxRunner, SandboxValidationError


class SandboxCodePayload(BaseModel):
    sandbox_id: str | None = None
    code: str


app = FastAPI(title="Spinbox Sandbox Runner", version="0.1.0")
default_root = Path(tempfile.gettempdir()) / "spinbox"
runner = MultiTenantSandboxRunner(Path(os.getenv("SPINBOX_SANDBOX_ROOT", str(default_root))))


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/sandboxes")
async def create_sandbox(payload: SandboxCodePayload, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _authorize_internal_request(authorization)
    if not payload.sandbox_id:
        raise HTTPException(status_code=400, detail="sandbox_id is required.")
    try:
        await runner.create_sandbox(payload.sandbox_id, payload.code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    return {"sandbox_id": payload.sandbox_id, "status": "created"}


@app.put("/internal/sandboxes/{sandbox_id}/file")
async def update_sandbox_file(
    sandbox_id: str,
    payload: SandboxCodePayload,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _authorize_internal_request(authorization)
    try:
        await runner.update_file(sandbox_id, payload.code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    return {"sandbox_id": sandbox_id, "status": "updated"}


@app.post("/internal/sandboxes/{sandbox_id}/validate", status_code=204)
async def validate_sandbox_file(
    sandbox_id: str,
    payload: SandboxCodePayload,
    authorization: str | None = Header(default=None),
) -> Response:
    _authorize_internal_request(authorization)
    try:
        await runner.validate_file(sandbox_id, payload.code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    return Response(status_code=204)


@app.post("/internal/sandboxes/{sandbox_id}/reset")
async def reset_sandbox(
    sandbox_id: str,
    payload: SandboxCodePayload,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _authorize_internal_request(authorization)
    try:
        await runner.reset_sandbox(sandbox_id, payload.code)
    except SandboxValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    return {"sandbox_id": sandbox_id, "status": "reset"}


@app.delete("/internal/sandboxes/{sandbox_id}")
async def delete_sandbox(sandbox_id: str, authorization: str | None = Header(default=None)) -> Response:
    _authorize_internal_request(authorization)
    await runner.delete_sandbox(sandbox_id)
    return Response(status_code=204)


@app.api_route(
    "/internal/sandboxes/{sandbox_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@app.api_route(
    "/internal/sandboxes/{sandbox_id}/{proxy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_sandbox_request(
    sandbox_id: str,
    request: Request,
    proxy_path: str = "",
    authorization: str | None = Header(default=None),
) -> Response:
    _authorize_internal_request(authorization)
    body = await request.body()
    status_code, headers, payload = await runner.proxy_request(
        sandbox_id,
        method=request.method,
        path=proxy_path,
        query_params=dict(request.query_params),
        headers={key: value for key, value in request.headers.items() if key.lower() != "authorization"},
        body=body or None,
    )
    if isinstance(payload, (dict, list, int, float, bool)) or payload is None:
        return JSONResponse(status_code=status_code, content=payload, headers=headers)
    return Response(status_code=status_code, content=payload, headers=headers)


def _authorize_internal_request(authorization: str | None) -> None:
    token = os.getenv("INTERNAL_API_TOKEN")
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")
