from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter


DEFAULT_RUNNER_COLLECTION = "spinbox-runners"
DEFAULT_FIRESTORE_DATABASE_ID = "(default)"


@dataclass(slots=True)
class RunnerRecord:
    """Persisted runner metadata used for capacity allocation."""

    service_name: str
    service_url: str
    pool_kind: str
    status: str
    max_sandboxes: int
    assigned_sandboxes: int
    created_at: datetime
    updated_at: datetime


class FirestoreRunnerRegistry:
    """Store runner lifecycle state in Firestore."""

    def __init__(
        self,
        *,
        collection_name: str | None = None,
        database_id: str | None = None,
        client: firestore.Client | None = None,
    ) -> None:
        self.collection_name = collection_name or os.getenv("RUNNER_REGISTRY_COLLECTION", DEFAULT_RUNNER_COLLECTION)
        self.database_id = database_id or os.getenv("FIRESTORE_DATABASE_ID", DEFAULT_FIRESTORE_DATABASE_ID)
        self._client = client or firestore.Client(database=self.database_id)
        self._collection = self._client.collection(self.collection_name)

    async def save(self, record: RunnerRecord) -> None:
        await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: RunnerRecord) -> None:
        self._collection.document(record.service_name).set(self._serialize(record))

    async def get(self, service_name: str) -> RunnerRecord | None:
        return await asyncio.to_thread(self._get_sync, service_name)

    def _get_sync(self, service_name: str) -> RunnerRecord | None:
        snapshot = self._collection.document(service_name).get()
        if not snapshot.exists:
            return None
        return self._deserialize(snapshot.to_dict() or {}, snapshot.id)

    async def delete(self, service_name: str) -> None:
        await asyncio.to_thread(self._delete_sync, service_name)

    def _delete_sync(self, service_name: str) -> None:
        self._collection.document(service_name).delete()

    async def list_all(self) -> list[RunnerRecord]:
        return await asyncio.to_thread(self._list_all_sync)

    def _list_all_sync(self) -> list[RunnerRecord]:
        return [self._deserialize(snapshot.to_dict() or {}, snapshot.id) for snapshot in self._collection.stream()]

    async def reserve_active_slot(self, *, prefer_pool_kind: tuple[str, ...] = ("warm", "overflow")) -> RunnerRecord | None:
        return await asyncio.to_thread(self._reserve_active_slot_sync, prefer_pool_kind)

    def _reserve_active_slot_sync(self, prefer_pool_kind: tuple[str, ...]) -> RunnerRecord | None:
        transaction = self._client.transaction()

        @firestore.transactional
        def reserve(transaction: firestore.Transaction) -> RunnerRecord | None:
            query = self._collection.where(filter=FieldFilter("status", "==", "active"))
            snapshots = list(query.stream(transaction=transaction))
            candidates = sorted(
                (self._deserialize(snapshot.to_dict() or {}, snapshot.id) for snapshot in snapshots),
                key=lambda record: (
                    _pool_kind_priority(record.pool_kind, prefer_pool_kind),
                    record.assigned_sandboxes,
                    record.service_name,
                ),
            )
            now = datetime.now(UTC)
            for candidate in candidates:
                if candidate.assigned_sandboxes >= candidate.max_sandboxes:
                    continue
                candidate.assigned_sandboxes += 1
                candidate.updated_at = now
                transaction.update(
                    self._collection.document(candidate.service_name),
                    {
                        "assigned_sandboxes": candidate.assigned_sandboxes,
                        "updated_at": _ensure_utc(candidate.updated_at),
                    },
                )
                return candidate
            return None

        return reserve(transaction)

    async def count_active_warm_runners(self) -> int:
        return await asyncio.to_thread(self._count_active_warm_runners_sync)

    def _count_active_warm_runners_sync(self) -> int:
        query = (
            self._collection.where(filter=FieldFilter("status", "==", "active"))
            .where(filter=FieldFilter("pool_kind", "==", "warm"))
        )
        return sum(1 for _ in query.stream())

    async def release_slot(self, service_name: str) -> RunnerRecord | None:
        return await asyncio.to_thread(self._release_slot_sync, service_name)

    def _release_slot_sync(self, service_name: str) -> RunnerRecord | None:
        transaction = self._client.transaction()

        @firestore.transactional
        def release(transaction: firestore.Transaction) -> RunnerRecord | None:
            ref = self._collection.document(service_name)
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = self._deserialize(snapshot.to_dict() or {}, snapshot.id)
            record.assigned_sandboxes = max(record.assigned_sandboxes - 1, 0)
            record.updated_at = datetime.now(UTC)
            if record.assigned_sandboxes == 0 and record.status != "error":
                record.status = "draining"
            transaction.update(
                ref,
                {
                    "status": record.status,
                    "assigned_sandboxes": record.assigned_sandboxes,
                    "updated_at": _ensure_utc(record.updated_at),
                },
            )
            return record

        return release(transaction)

    def _serialize(self, record: RunnerRecord) -> dict[str, object]:
        return {
            "service_name": record.service_name,
            "service_url": record.service_url,
            "pool_kind": record.pool_kind,
            "status": record.status,
            "max_sandboxes": record.max_sandboxes,
            "assigned_sandboxes": record.assigned_sandboxes,
            "created_at": _ensure_utc(record.created_at),
            "updated_at": _ensure_utc(record.updated_at),
        }

    def _deserialize(self, payload: dict[str, object], service_name: str) -> RunnerRecord:
        return RunnerRecord(
            service_name=str(payload.get("service_name") or service_name),
            service_url=str(payload.get("service_url") or ""),
            pool_kind=str(payload.get("pool_kind") or "overflow"),
            status=str(payload.get("status") or "provisioning"),
            max_sandboxes=int(payload.get("max_sandboxes") or 0),
            assigned_sandboxes=int(payload.get("assigned_sandboxes") or 0),
            created_at=_coerce_datetime(payload.get("created_at")),
            updated_at=_coerce_datetime(payload.get("updated_at")),
        )


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    raise ValueError(f"Expected datetime value from Firestore, received {type(value)!r}")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _pool_kind_priority(pool_kind: str, prefer_pool_kind: tuple[str, ...]) -> int:
    try:
        return prefer_pool_kind.index(pool_kind)
    except ValueError:
        return len(prefer_pool_kind)
