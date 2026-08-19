from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException

from app.services.gcp import GCPClient, GCPConfigurationError, GCPOperationError
from app.services.route_parser import RouteDefinition, RouteValidationError, parse_routes_file
from app.services.runner_registry import FirestoreRunnerRegistry, RunnerRecord
from app.services.sandbox_client import HTTPError, ResponseSpec, SandboxRuntimeClient
from app.services.sandbox_registry import FirestoreSandboxRegistry, SandboxRecord

logger = logging.getLogger(__name__)

ROUTES_FILE_PATH = "/app/routes.py"
DEFAULT_TTL_SECONDS = 60 * 60
DEFAULT_RUNNER_MAX_SANDBOXES = 10
DEFAULT_RUNNER_WARM_POOL_SIZE = 10
TESTER_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SandboxLifecycleState = Literal["loading", "active", "error", "expired"]

DEFAULT_ROUTES_FILE = """from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from database import Base, get_db

router = APIRouter()


# --- Models (ORM) ---

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    age = Column(Integer, nullable=True)


# --- Pydantic schema ---

class User(BaseModel):
    name: str
    email: str
    age: Optional[int] = None


# --- Routes ---

@router.get("/")
def root():
    return {"message": "Spinbox sandbox is running!"}


@router.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(UserDB).all()
    return {"users": users, "count": len(users)}


@router.post("/users", status_code=201)
def create_user(user: User, db: Session = Depends(get_db)):
    new_user = UserDB(**user.dict())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return {"message": f"User {user_id} deleted"}
"""


class SandboxManager:
    """Own sandbox lifecycle, stored routes.py, proxying, and expiration."""

    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        gcp_client: GCPClient | None = None,
        runtime_client: SandboxRuntimeClient | None = None,
        registry: FirestoreSandboxRegistry | None = None,
        runner_registry: FirestoreRunnerRegistry | None = None,
    ) -> None:
        ttl_from_env = int(os.getenv("SANDBOX_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else ttl_from_env
        self.runner_max_sandboxes = int(os.getenv("RUNNER_MAX_SANDBOXES", str(DEFAULT_RUNNER_MAX_SANDBOXES)))
        self.runner_warm_pool_size = int(os.getenv("RUNNER_WARM_POOL_SIZE", str(DEFAULT_RUNNER_WARM_POOL_SIZE)))
        self._lock = asyncio.Lock()
        self._gcp = gcp_client or GCPClient()
        self._runtime = runtime_client or SandboxRuntimeClient(require_auth=True)
        self._registry = registry or FirestoreSandboxRegistry()
        self._runner_registry = runner_registry or FirestoreRunnerRegistry()
        self._startup_tasks: dict[str, asyncio.Task[None]] = {}
        self._reconcile_task: asyncio.Task[None] | None = None

    async def create_sandbox(self) -> SandboxRecord:
        sandbox_id = secrets.token_hex(4)
        routes = self._parse_routes(DEFAULT_ROUTES_FILE)
        created_at = datetime.now(UTC)

        sandbox = SandboxRecord(
            id=sandbox_id,
            service_name="",
            service_url="",
            file_content=DEFAULT_ROUTES_FILE,
            routes=routes,
            status="loading",
            error_detail=None,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self.ttl_seconds),
        )
        await self._registry.save(sandbox)
        async with self._lock:
            self._startup_tasks[sandbox_id] = asyncio.create_task(self._provision_sandbox(sandbox_id))
        self._schedule_reconcile_warm_pool()
        return sandbox

    async def get_sandbox(self, sandbox_id: str) -> SandboxRecord:
        sandbox = await self._peek_sandbox(sandbox_id)
        if sandbox.expires_at <= datetime.now(UTC):
            await self._expire_sandbox(sandbox_id)
            raise HTTPException(status_code=404, detail="Sandbox expired")
        sandbox = await self._ensure_assigned_runner_live(sandbox)
        return sandbox

    async def get_summary(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = await self.get_sandbox(sandbox_id)
        return self._serialize_sandbox(sandbox)

    async def get_file(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = await self._require_ready_sandbox(sandbox_id)
        return {"id": sandbox.id, "path": ROUTES_FILE_PATH, "content": sandbox.file_content}

    async def get_routes(self, sandbox_id: str) -> list[dict[str, Any]]:
        sandbox = await self._require_ready_sandbox(sandbox_id)
        return [self._serialize_route(route) for route in sandbox.routes if route.method in TESTER_METHODS]

    async def update_file(self, sandbox_id: str, content: str) -> dict[str, Any]:
        routes = self._parse_routes(content)
        sandbox = await self._require_ready_sandbox(sandbox_id)

        try:
            await self._runtime.update_routes(sandbox.service_url, sandbox_id, content)
        except HTTPError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        sandbox.file_content = content
        sandbox.routes = routes
        await self._registry.save(sandbox)

        return {"id": sandbox_id, "path": ROUTES_FILE_PATH, "content": content}

    async def validate_file(self, sandbox_id: str, content: str) -> None:
        self._parse_routes(content)
        sandbox = await self._require_ready_sandbox(sandbox_id)

        try:
            await self._runtime.validate_routes(sandbox.service_url, sandbox_id, content)
        except HTTPError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    async def reset_sandbox(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = await self.get_sandbox(sandbox_id)
        if sandbox.status == "loading":
            raise HTTPException(status_code=409, detail="Sandbox is still starting.")

        now = datetime.now(UTC)
        sandbox.status = "loading"
        sandbox.error_detail = None
        sandbox.created_at = now
        sandbox.expires_at = now + timedelta(seconds=self.ttl_seconds)
        sandbox.file_content = DEFAULT_ROUTES_FILE
        sandbox.routes = self._parse_routes(DEFAULT_ROUTES_FILE)
        await self._registry.save(sandbox)
        try:
            await self._runtime.reset_sandbox(sandbox.service_url, sandbox_id, DEFAULT_ROUTES_FILE)
        except HTTPError as exc:
            sandbox.status = "error"
            sandbox.error_detail = str(exc.detail)
            await self._registry.save(sandbox)
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        sandbox.status = "active"
        await self._registry.save(sandbox)
        return {"id": sandbox_id, "message": "Sandbox reset"}

    async def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox = await self._peek_sandbox(sandbox_id)
        async with self._lock:
            self._startup_tasks.pop(sandbox_id, None)
        await self._delete_sandbox_record_and_release_runner(sandbox)
        self._schedule_reconcile_warm_pool()

    async def proxy_request(
        self,
        sandbox_id: str,
        *,
        method: str,
        path: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        raw_body: str | None,
    ) -> ResponseSpec:
        sandbox = await self._require_ready_sandbox(sandbox_id)

        try:
            return await self._runtime.proxy_request(
                sandbox.service_url,
                sandbox.id,
                method=method,
                path=path,
                query_params=query_params,
                headers=headers,
                raw_body=raw_body,
            )
        except HTTPError:
            raise

    async def cleanup_expired(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        deleted = 0
        expired = await self._registry.list_expired(now)
        for sandbox in expired:
            await self._delete_sandbox_record_and_release_runner(sandbox)
            deleted += 1

        deleted += await self._reconcile_runner_drift(now=now, cleanup_orphans=True)

        active_records = await self._registry.list_all()
        await self.reconcile_warm_pool()
        remaining = sum(1 for record in active_records if record.expires_at > now)
        return {"deleted": deleted, "remaining": remaining}

    async def _peek_sandbox(self, sandbox_id: str) -> SandboxRecord:
        sandbox = await self._registry.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=404, detail="Sandbox not found")
        return sandbox

    async def _require_ready_sandbox(self, sandbox_id: str) -> SandboxRecord:
        sandbox = await self.get_sandbox(sandbox_id)
        if sandbox.status == "loading":
            raise HTTPException(status_code=409, detail="Sandbox is still starting.")
        if sandbox.status == "error":
            raise HTTPException(status_code=502, detail=sandbox.error_detail or "Sandbox failed to start.")
        return sandbox

    async def _expire_sandbox(self, sandbox_id: str) -> None:
        sandbox = await self._registry.get(sandbox_id)
        if sandbox is None:
            return
        await self._delete_sandbox_record_and_release_runner(sandbox)

    async def _provision_sandbox(self, sandbox_id: str) -> None:
        runner: RunnerRecord | None = None
        created_runner = False
        try:
            await self._reconcile_runner_drift(now=datetime.now(UTC), cleanup_orphans=True)
            runner = await self._reserve_live_runner()
            if runner is None:
                runner = await self._create_runner(pool_kind="overflow", assigned_sandboxes=1)
                created_runner = True

            current = await self._registry.get(sandbox_id)
            if current is None:
                await self._release_runner_slot(runner.service_name)
                return

            current.service_name = runner.service_name
            current.service_url = runner.service_url
            await self._registry.save(current)
            await self._runtime.create_sandbox(runner.service_url, sandbox_id, current.file_content)
        except (GCPConfigurationError, GCPOperationError, HTTPError) as exc:
            if runner is not None:
                try:
                    await self._release_runner_slot(runner.service_name)
                except (GCPConfigurationError, GCPOperationError, HTTPError):
                    pass
            current = await self._registry.get(sandbox_id)
            if current is not None:
                current.status = "error"
                current.error_detail = f"Runner provisioning failed: {exc}"
                await self._registry.save(current)
            async with self._lock:
                self._startup_tasks.pop(sandbox_id, None)
            return

        current = await self._registry.get(sandbox_id)
        if current is None:
            try:
                await self._runtime.delete_sandbox(runner.service_url, sandbox_id)
            except HTTPError:
                pass
            await self._release_runner_slot(runner.service_name)
            return

        current.service_name = runner.service_name
        current.service_url = runner.service_url
        current.status = "active"
        current.error_detail = None
        await self._registry.save(current)

        if created_runner:
            refreshed_runner = await self._runner_registry.get(runner.service_name)
            if refreshed_runner is not None:
                refreshed_runner.status = "active"
                refreshed_runner.updated_at = datetime.now(UTC)
                await self._runner_registry.save(refreshed_runner)

        async with self._lock:
            self._startup_tasks.pop(sandbox_id, None)
        self._schedule_reconcile_warm_pool()

    async def wait_for_sandbox_startup(self, sandbox_id: str) -> None:
        async with self._lock:
            task = self._startup_tasks.get(sandbox_id)
        if task is not None:
            await asyncio.shield(task)

    async def reconcile_warm_pool(self) -> None:
        while True:
            await self._reconcile_runner_drift(now=datetime.now(UTC), cleanup_orphans=True)
            warm_count = await self._trim_excess_warm_runners()
            if warm_count >= self.runner_warm_pool_size:
                return

            try:
                runner = await self._create_runner(pool_kind="warm", assigned_sandboxes=0)
                runner.status = "active"
                runner.updated_at = datetime.now(UTC)
                await self._runner_registry.save(runner)
            except (GCPConfigurationError, GCPOperationError) as exc:
                logger.warning("Warm pool reconcile failed before reaching target", exc_info=exc)
                return

    async def wait_for_reconcile(self) -> None:
        async with self._lock:
            task = self._reconcile_task
        if task is not None:
            await asyncio.shield(task)

    def _serialize_sandbox(self, sandbox: SandboxRecord) -> dict[str, Any]:
        ttl_seconds = max(int((sandbox.expires_at - datetime.now(UTC)).total_seconds()), 0)
        return {
            "id": sandbox.id,
            "url": f"/sandbox/{sandbox.id}",
            "placeholder_url": sandbox.service_url,
            "status": sandbox.status,
            "error_detail": sandbox.error_detail,
            "created_at": sandbox.created_at,
            "expires_at": sandbox.expires_at,
            "ttl_seconds": ttl_seconds,
        }

    def _serialize_route(self, route: RouteDefinition) -> dict[str, Any]:
        return {"method": route.method, "path": route.path, "param_names": route.param_names}

    def _parse_routes(self, content: str) -> list[RouteDefinition]:
        try:
            return parse_routes_file(content)
        except RouteValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Sandbox validation failed",
                    "detail": f"Could not apply routes.py: {exc.message}",
                    "kind": exc.kind,
                    "line": exc.line,
                    "column": exc.column,
                },
            ) from exc

    async def _delete_cloud_run_service_if_present(self, service_name: str) -> None:
        if not service_name:
            return
        await self._gcp.delete_runner(service_name)

    async def _reserve_live_runner(self) -> RunnerRecord | None:
        while True:
            runner = await self._runner_registry.reserve_active_slot(prefer_pool_kind=("warm", "overflow"))
            if runner is None:
                return None

            live_service = await self._gcp.get_runner(runner.service_name)
            if live_service is None:
                logger.warning("Removing stale runner registry record for missing Cloud Run service %s", runner.service_name)
                await self._runner_registry.delete(runner.service_name)
                continue

            if live_service.service_url and live_service.service_url != runner.service_url:
                runner.service_url = live_service.service_url
                runner.updated_at = datetime.now(UTC)
                await self._runner_registry.save(runner)

            return runner

    async def _ensure_assigned_runner_live(self, sandbox: SandboxRecord) -> SandboxRecord:
        if sandbox.status != "active" or not sandbox.service_name:
            return sandbox

        runner = await self._gcp.get_runner(sandbox.service_name)
        if runner is not None:
            if runner.service_url and runner.service_url != sandbox.service_url:
                sandbox.service_url = runner.service_url
                await self._registry.save(sandbox)
            return sandbox

        sandbox.status = "error"
        sandbox.error_detail = f"Assigned runner is missing: {sandbox.service_name}"
        await self._registry.save(sandbox)
        logger.warning("Sandbox %s marked error because assigned runner %s is missing", sandbox.id, sandbox.service_name)
        return sandbox

    async def _reconcile_runner_drift(self, *, now: datetime, cleanup_orphans: bool) -> int:
        deleted = 0
        active_records = await self._registry.list_all()
        live_runner_counts = self._live_runner_counts(active_records, now=now)
        orphan_cutoff = now - timedelta(seconds=self.ttl_seconds)
        runner_records = await self._runner_registry.list_all()
        runner_services = await self._gcp.list_runners()
        runner_service_map = {service.service_name: service for service in runner_services}
        cleaned_runner_services: set[str] = set()

        for runner in runner_records:
            live_service = runner_service_map.get(runner.service_name)
            if live_service is None:
                logger.warning("Deleting stale runner record with no Cloud Run service: %s", runner.service_name)
                await self._runner_registry.delete(runner.service_name)
                deleted += 1
                continue

            live_count = live_runner_counts.get(runner.service_name, 0)
            if (
                live_count != runner.assigned_sandboxes
                or runner.service_url != live_service.service_url
            ):
                runner.assigned_sandboxes = live_count
                runner.service_url = live_service.service_url
                runner.updated_at = now
                if runner.status != "error":
                    runner.status = "active" if live_count > 0 or runner.pool_kind == "warm" else "draining"
                await self._runner_registry.save(runner)

            if live_count == 0 and runner.pool_kind != "warm":
                if cleanup_orphans:
                    logger.info("Deleting empty overflow runner %s during reconciliation", runner.service_name)
                    await self._delete_cloud_run_service_if_present(runner.service_name)
                    cleaned_runner_services.add(runner.service_name)
                    await self._runner_registry.delete(runner.service_name)
                    deleted += 1

        if cleanup_orphans:
            known_runner_names = {runner.service_name for runner in await self._runner_registry.list_all()}
            for service in runner_services:
                if service.service_name in cleaned_runner_services:
                    continue
                if service.service_name in known_runner_names:
                    continue
                if service.create_time is not None and service.create_time > orphan_cutoff:
                    continue
                logger.warning("Deleting orphaned Cloud Run runner with no registry record: %s", service.service_name)
                try:
                    await self._delete_cloud_run_service_if_present(service.service_name)
                except (GCPConfigurationError, GCPOperationError):
                    continue
                deleted += 1

        return deleted

    async def _trim_excess_warm_runners(self) -> int:
        runners = await self._runner_registry.list_all()
        warm_runners = [
            runner
            for runner in runners
            if runner.pool_kind == "warm" and runner.status == "active"
        ]
        excess = len(warm_runners) - self.runner_warm_pool_size
        if excess <= 0:
            return len(warm_runners)

        idle_warm_runners = sorted(
            (runner for runner in warm_runners if runner.assigned_sandboxes == 0),
            key=lambda runner: (runner.updated_at, runner.created_at, runner.service_name),
            reverse=True,
        )
        trimmed = 0
        for runner in idle_warm_runners[:excess]:
            logger.info("Trimming excess warm runner %s to enforce pool target", runner.service_name)
            try:
                await self._delete_cloud_run_service_if_present(runner.service_name)
            except (GCPConfigurationError, GCPOperationError):
                continue
            await self._runner_registry.delete(runner.service_name)
            trimmed += 1

        return len(warm_runners) - trimmed

    def _schedule_reconcile_warm_pool(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def runner() -> None:
            try:
                await self.reconcile_warm_pool()
            finally:
                async with self._lock:
                    if self._reconcile_task is task:
                        self._reconcile_task = None

        async def ensure_task() -> None:
            async with self._lock:
                current = self._reconcile_task
                if current is not None and not current.done():
                    return
                nonlocal task
                task = loop.create_task(runner())
                self._reconcile_task = task

        task: asyncio.Task[None] | None = None
        loop.create_task(ensure_task())

    async def _create_runner(self, *, pool_kind: str, assigned_sandboxes: int) -> RunnerRecord:
        runner_id = secrets.token_hex(4)
        cloud_run_runner = await self._gcp.create_runner(runner_id)
        now = datetime.now(UTC)
        record = RunnerRecord(
            service_name=cloud_run_runner.service_name,
            service_url=cloud_run_runner.service_url,
            pool_kind=pool_kind,
            status="provisioning",
            max_sandboxes=self.runner_max_sandboxes,
            assigned_sandboxes=assigned_sandboxes,
            created_at=now,
            updated_at=now,
        )
        await self._runner_registry.save(record)
        return record

    async def _release_runner_slot(self, service_name: str) -> None:
        if not service_name:
            return
        runner = await self._runner_registry.release_slot(service_name)
        if runner is None:
            return
        live_count = await self._live_runner_count_for_service(service_name)
        if live_count != runner.assigned_sandboxes:
            runner.assigned_sandboxes = live_count
            runner.updated_at = datetime.now(UTC)
            if runner.status != "error":
                runner.status = "active" if live_count > 0 or runner.pool_kind == "warm" else "draining"
            await self._runner_registry.save(runner)
        if live_count > 0:
            return
        if runner.pool_kind == "warm":
            runner.status = "active"
            runner.updated_at = datetime.now(UTC)
            await self._runner_registry.save(runner)
            return
        await self._delete_cloud_run_service_if_present(runner.service_name)
        await self._runner_registry.delete(runner.service_name)

    async def _delete_sandbox_record_and_release_runner(self, sandbox: SandboxRecord) -> None:
        try:
            if sandbox.service_url:
                await self._runtime.delete_sandbox(sandbox.service_url, sandbox.id)
        except HTTPError:
            pass
        await self._registry.delete(sandbox.id)
        async with self._lock:
            self._startup_tasks.pop(sandbox.id, None)
        try:
            await self._release_runner_slot(sandbox.service_name)
        except (GCPConfigurationError, GCPOperationError, HTTPError):
            pass
        self._schedule_reconcile_warm_pool()

    async def _live_runner_count_for_service(self, service_name: str) -> int:
        if not service_name:
            return 0
        counts = self._live_runner_counts(await self._registry.list_all(), now=datetime.now(UTC))
        return counts.get(service_name, 0)

    def _live_runner_counts(self, sandboxes: list[SandboxRecord], *, now: datetime) -> dict[str, int]:
        counts = Counter(
            sandbox.service_name
            for sandbox in sandboxes
            if sandbox.service_name and sandbox.expires_at > now
        )
        return dict(counts)
