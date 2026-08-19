from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SandboxResponse(BaseModel):
    """Serialized sandbox metadata returned to the frontend."""

    id: str
    url: str
    placeholder_url: str
    status: str
    error_detail: str | None = None
    created_at: datetime
    expires_at: datetime
    ttl_seconds: int


class SandboxFileResponse(BaseModel):
    """Represents the editable sandbox file exposed by the backend."""

    id: str
    path: str
    content: str


class SandboxFileUpdate(BaseModel):
    """Payload used to replace the current in-memory routes file."""

    content: str


class SandboxRouteResponse(BaseModel):
    """Represents a tester-visible route compiled from the sandbox file."""

    method: str
    path: str
    param_names: list[str]


class ResetSandboxResponse(BaseModel):
    """Acknowledges that a sandbox was reset to its initial state."""

    id: str
    message: str


class ErrorResponse(BaseModel):
    """Generic error shape used for structured backend failures."""

    detail: Any
