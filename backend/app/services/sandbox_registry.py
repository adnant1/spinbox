from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.services.route_parser import RouteDefinition


DEFAULT_SANDBOX_COLLECTION = "spinbox-sandboxes"
DEFAULT_FIRESTORE_DATABASE_ID = "(default)"


@dataclass(slots=True)
class SandboxRecord:
    """Persisted sandbox metadata stored outside the backend process."""

    id: str
    service_name: str
    service_url: str
    file_content: str
    routes: list[RouteDefinition]
    status: str
    error_detail: str | None
    created_at: datetime
    expires_at: datetime


class FirestoreSandboxRegistry:
    """Store sandbox lifecycle state in Firestore so cleanup survives scale-to-zero."""

    def __init__(
        self,
        *,
        collection_name: str | None = None,
        database_id: str | None = None,
        client: firestore.Client | None = None,
    ) -> None:
        self.collection_name = collection_name or os.getenv("SANDBOX_REGISTRY_COLLECTION", DEFAULT_SANDBOX_COLLECTION)
        self.database_id = database_id or os.getenv("FIRESTORE_DATABASE_ID", DEFAULT_FIRESTORE_DATABASE_ID)
        self._client = client or firestore.Client(database=self.database_id)
        self._collection = self._client.collection(self.collection_name)

    async def save(self, record: SandboxRecord) -> None:
        await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: SandboxRecord) -> None:
        self._collection.document(record.id).set(self._serialize(record))

    async def get(self, sandbox_id: str) -> SandboxRecord | None:
        return await asyncio.to_thread(self._get_sync, sandbox_id)

    def _get_sync(self, sandbox_id: str) -> SandboxRecord | None:
        snapshot = self._collection.document(sandbox_id).get()
        if not snapshot.exists:
            return None
        return self._deserialize(snapshot.to_dict() or {}, snapshot.id)

    async def delete(self, sandbox_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, sandbox_id)

    def _delete_sync(self, sandbox_id: str) -> None:
        self._collection.document(sandbox_id).delete()

    async def list_all(self) -> list[SandboxRecord]:
        return await asyncio.to_thread(self._list_all_sync)

    def _list_all_sync(self) -> list[SandboxRecord]:
        return [self._deserialize(snapshot.to_dict() or {}, snapshot.id) for snapshot in self._collection.stream()]

    async def list_expired(self, now: datetime) -> list[SandboxRecord]:
        return await asyncio.to_thread(self._list_expired_sync, now)

    def _list_expired_sync(self, now: datetime) -> list[SandboxRecord]:
        query = self._collection.where(filter=FieldFilter("expires_at", "<=", now))
        return [self._deserialize(snapshot.to_dict() or {}, snapshot.id) for snapshot in query.stream()]

    def _serialize(self, record: SandboxRecord) -> dict[str, object]:
        return {
            "sandbox_id": record.id,
            "service_name": record.service_name,
            "service_url": record.service_url,
            "file_content": record.file_content,
            "routes": [self._serialize_route(route) for route in record.routes],
            "status": record.status,
            "error_detail": record.error_detail,
            "created_at": _ensure_utc(record.created_at),
            "expires_at": _ensure_utc(record.expires_at),
        }

    def _deserialize(self, payload: dict[str, object], sandbox_id: str) -> SandboxRecord:
        routes_payload = payload.get("routes", [])
        routes = [self._deserialize_route(route_payload) for route_payload in routes_payload if isinstance(route_payload, dict)]

        return SandboxRecord(
            id=str(payload.get("sandbox_id") or sandbox_id),
            service_name=str(payload.get("service_name") or ""),
            service_url=str(payload.get("service_url") or ""),
            file_content=str(payload.get("file_content") or ""),
            routes=routes,
            status=str(payload.get("status") or "loading"),
            error_detail=_coerce_optional_str(payload.get("error_detail")),
            created_at=_coerce_datetime(payload.get("created_at")),
            expires_at=_coerce_datetime(payload.get("expires_at")),
        )

    @staticmethod
    def _serialize_route(route: RouteDefinition) -> dict[str, object]:
        return {
            "method": route.method,
            "path": route.path,
            "param_names": route.param_names,
        }

    @staticmethod
    def _deserialize_route(payload: dict[str, object]) -> RouteDefinition:
        raw_params = payload.get("param_names", [])
        if not isinstance(raw_params, list):
            raw_params = []
        return RouteDefinition(
            method=str(payload.get("method") or ""),
            path=str(payload.get("path") or "/"),
            param_names=[str(value) for value in raw_params],
        )


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    stringified = str(value)
    return stringified or None


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    raise ValueError(f"Expected datetime value from Firestore, received {type(value)!r}")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
