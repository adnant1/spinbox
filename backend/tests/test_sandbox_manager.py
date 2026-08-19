from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.services.gcp import GCPOperationError, CloudRunService, CloudRunServiceRecord
from app.services.route_parser import RouteDefinition
from app.services.runner_registry import RunnerRecord
from app.services.sandbox_client import HTTPError, ResponseSpec
from app.services.sandbox_manager import DEFAULT_ROUTES_FILE, SandboxManager
from app.services.sandbox_registry import SandboxRecord


os.environ.setdefault("RUNNER_WARM_POOL_SIZE", "0")


UPDATED_ROUTES_FILE = """
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def root():
    return {"ok": True}

@router.post("/users")
def create_user():
    return {"created": True}
"""


class FakeGCPClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.services: dict[str, CloudRunServiceRecord] = {}
        self.fail_on_create = False
        self.create_gate = asyncio.Event()
        self.create_gate.set()

    async def create_runner(self, runner_id: str) -> CloudRunService:
        await self.create_gate.wait()
        if self.fail_on_create:
            raise GCPOperationError("Cloud Run service failed to start")
        service_name = f"spinbox-runner-{runner_id}"
        self.created.append(service_name)
        runner = CloudRunService(service_name=service_name, service_url=f"https://{service_name}.run.app")
        self.services[runner.service_name] = CloudRunServiceRecord(
            service_name=runner.service_name,
            service_url=runner.service_url,
            create_time=datetime.now(UTC),
        )
        return runner

    async def delete_runner(self, service_name: str) -> None:
        self.deleted.append(service_name)
        self.services.pop(service_name, None)

    async def list_runners(self) -> list[CloudRunServiceRecord]:
        return list(self.services.values())

    async def get_runner(self, service_name: str) -> CloudRunServiceRecord | None:
        return self.services.get(service_name)


class FakeRuntimeClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []
        self.updated: list[tuple[str, str, str]] = []
        self.resets: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.fail_on_update = False
        self.validate_error: HTTPError | None = None

    async def create_sandbox(self, runner_url: str, sandbox_id: str, code: str) -> None:
        self.created.append((runner_url, sandbox_id, code))

    async def update_routes(self, runner_url: str, sandbox_id: str, code: str) -> None:
        if self.fail_on_update:
            raise HTTPError(500, {"detail": "sandbox update failed"})
        self.updated.append((runner_url, sandbox_id, code))

    async def reset_sandbox(self, runner_url: str, sandbox_id: str, code: str) -> None:
        self.resets.append((runner_url, sandbox_id, code))

    async def validate_routes(self, runner_url: str, sandbox_id: str, code: str) -> None:
        if self.validate_error is not None:
            raise self.validate_error

    async def delete_sandbox(self, runner_url: str, sandbox_id: str) -> None:
        self.deleted.append((runner_url, sandbox_id))

    async def proxy_request(self, runner_url: str, sandbox_id: str, **_: object) -> ResponseSpec:
        return ResponseSpec(
            body={"runner_url": runner_url, "sandbox_id": sandbox_id},
            status_code=200,
            headers={"content-type": "application/json"},
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[str, SandboxRecord] = {}

    async def save(self, record: SandboxRecord) -> None:
        self.records[record.id] = _clone_record(record)

    async def get(self, sandbox_id: str) -> SandboxRecord | None:
        record = self.records.get(sandbox_id)
        if record is None:
            return None
        return _clone_record(record)

    async def delete(self, sandbox_id: str) -> None:
        self.records.pop(sandbox_id, None)

    async def list_all(self) -> list[SandboxRecord]:
        return [_clone_record(record) for record in self.records.values()]

    async def list_expired(self, now: datetime) -> list[SandboxRecord]:
        return [_clone_record(record) for record in self.records.values() if record.expires_at <= now]


class FakeRunnerRegistry:
    def __init__(self) -> None:
        self.records: dict[str, RunnerRecord] = {}

    async def save(self, record: RunnerRecord) -> None:
        self.records[record.service_name] = _clone_runner(record)

    async def get(self, service_name: str) -> RunnerRecord | None:
        record = self.records.get(service_name)
        if record is None:
            return None
        return _clone_runner(record)

    async def delete(self, service_name: str) -> None:
        self.records.pop(service_name, None)

    async def list_all(self) -> list[RunnerRecord]:
        return [_clone_runner(record) for record in self.records.values()]

    async def reserve_active_slot(self, *, prefer_pool_kind: tuple[str, ...] = ("warm", "overflow")) -> RunnerRecord | None:
        candidates = sorted(
            (
                _clone_runner(record)
                for record in self.records.values()
                if record.status == "active" and record.assigned_sandboxes < record.max_sandboxes
            ),
            key=lambda record: (
                prefer_pool_kind.index(record.pool_kind) if record.pool_kind in prefer_pool_kind else len(prefer_pool_kind),
                record.assigned_sandboxes,
                record.service_name,
            ),
        )
        if not candidates:
            return None
        selected = candidates[0]
        selected.assigned_sandboxes += 1
        selected.updated_at = datetime.now(UTC)
        self.records[selected.service_name] = _clone_runner(selected)
        return selected

    async def count_active_warm_runners(self) -> int:
        return sum(1 for record in self.records.values() if record.status == "active" and record.pool_kind == "warm")

    async def release_slot(self, service_name: str) -> RunnerRecord | None:
        record = self.records.get(service_name)
        if record is None:
            return None
        record = _clone_runner(record)
        record.assigned_sandboxes = max(record.assigned_sandboxes - 1, 0)
        if record.assigned_sandboxes == 0 and record.pool_kind != "warm":
            record.status = "draining"
        record.updated_at = datetime.now(UTC)
        self.records[service_name] = _clone_runner(record)
        return record


def _clone_record(record: SandboxRecord) -> SandboxRecord:
    return SandboxRecord(
        id=record.id,
        service_name=record.service_name,
        service_url=record.service_url,
        file_content=record.file_content,
        routes=[
            RouteDefinition(method=route.method, path=route.path, param_names=list(route.param_names))
            for route in record.routes
        ],
        status=record.status,
        error_detail=record.error_detail,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


def _clone_runner(record: RunnerRecord) -> RunnerRecord:
    return RunnerRecord(
        service_name=record.service_name,
        service_url=record.service_url,
        pool_kind=record.pool_kind,
        status=record.status,
        max_sandboxes=record.max_sandboxes,
        assigned_sandboxes=record.assigned_sandboxes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def test_create_sandbox_returns_immediately_and_finishes_in_background() -> None:
    async def scenario() -> None:
        gcp = FakeGCPClient()
        runtime = FakeRuntimeClient()
        registry = FakeRegistry()
        runner_registry = FakeRunnerRegistry()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=runtime,
            registry=registry,
            runner_registry=runner_registry,
        )

        gcp.create_gate.clear()
        sandbox = await manager.create_sandbox()
        summary = await manager.get_summary(sandbox.id)

        assert summary["status"] == "loading"
        assert gcp.created == []

        gcp.create_gate.set()
        await manager.wait_for_sandbox_startup(sandbox.id)

        summary = await manager.get_summary(sandbox.id)
        file_info = await manager.get_file(sandbox.id)
        routes = await manager.get_routes(sandbox.id)
        stored = await registry.get(sandbox.id)

        assert stored is not None
        assert len(gcp.created) == 1
        assert runtime.created == [(stored.service_url, sandbox.id, DEFAULT_ROUTES_FILE)]
        assert summary["status"] == "active"
        assert summary["url"] == f"/sandbox/{sandbox.id}"
        assert summary["placeholder_url"] == stored.service_url
        assert file_info["content"] == DEFAULT_ROUTES_FILE
        assert [route["path"] for route in routes] == ["/", "/users", "/users", "/users/{user_id}", "/users/{user_id}"]

    asyncio.run(scenario())


def test_create_sandbox_reuses_existing_runner_capacity() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        runner_registry = FakeRunnerRegistry()
        existing_runner = RunnerRecord(
            service_name="spinbox-runner-existing",
            service_url="https://spinbox-runner-existing.run.app",
            pool_kind="warm",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=1,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(existing_runner)
        gcp = FakeGCPClient()
        gcp.services[existing_runner.service_name] = CloudRunServiceRecord(
            service_name=existing_runner.service_name,
            service_url=existing_runner.service_url,
            create_time=now,
        )

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=runner_registry,
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        stored = await manager.get_sandbox(sandbox.id)
        runner = await runner_registry.get(existing_runner.service_name)

        assert stored.service_name == existing_runner.service_name
        assert runner is not None
        assert runner.assigned_sandboxes == 1

    asyncio.run(scenario())


def test_create_sandbox_prefers_warm_runner_before_overflow() -> None:
    async def scenario() -> None:
        previous = os.environ.get("RUNNER_WARM_POOL_SIZE")
        os.environ["RUNNER_WARM_POOL_SIZE"] = "10"
        now = datetime.now(UTC)
        try:
            runner_registry = FakeRunnerRegistry()
            warm_runner = RunnerRecord(
                service_name="spinbox-runner-warm",
                service_url="https://spinbox-runner-warm.run.app",
                pool_kind="warm",
                status="active",
                max_sandboxes=5,
                assigned_sandboxes=1,
                created_at=now,
                updated_at=now,
            )
            overflow_runner = RunnerRecord(
                service_name="spinbox-runner-overflow",
                service_url="https://spinbox-runner-overflow.run.app",
                pool_kind="overflow",
                status="active",
                max_sandboxes=5,
                assigned_sandboxes=0,
                created_at=now,
                updated_at=now,
            )
            await runner_registry.save(warm_runner)
            await runner_registry.save(overflow_runner)
            gcp = FakeGCPClient()
            gcp.services[warm_runner.service_name] = CloudRunServiceRecord(
                service_name=warm_runner.service_name,
                service_url=warm_runner.service_url,
                create_time=now,
            )
            gcp.services[overflow_runner.service_name] = CloudRunServiceRecord(
                service_name=overflow_runner.service_name,
                service_url=overflow_runner.service_url,
                create_time=now,
            )

            manager = SandboxManager(
                ttl_seconds=3600,
                gcp_client=gcp,
                runtime_client=FakeRuntimeClient(),
                registry=FakeRegistry(),
                runner_registry=runner_registry,
            )

            sandbox = await manager.create_sandbox()
            await manager.wait_for_sandbox_startup(sandbox.id)
            stored = await manager.get_sandbox(sandbox.id)

            assert stored.service_name == warm_runner.service_name
        finally:
            if previous is None:
                os.environ.pop("RUNNER_WARM_POOL_SIZE", None)
            else:
                os.environ["RUNNER_WARM_POOL_SIZE"] = previous

    asyncio.run(scenario())


def test_create_sandbox_bursts_with_overflow_when_warm_pool_is_full() -> None:
    async def scenario() -> None:
        previous = os.environ.get("RUNNER_WARM_POOL_SIZE")
        os.environ["RUNNER_WARM_POOL_SIZE"] = "10"
        now = datetime.now(UTC)
        try:
            gcp = FakeGCPClient()
            runner_registry = FakeRunnerRegistry()
            warm_runner = RunnerRecord(
                service_name="spinbox-runner-warm-full",
                service_url="https://spinbox-runner-warm-full.run.app",
                pool_kind="warm",
                status="active",
                max_sandboxes=10,
                assigned_sandboxes=10,
                created_at=now,
                updated_at=now,
            )
            await runner_registry.save(warm_runner)

            manager = SandboxManager(
                ttl_seconds=3600,
                gcp_client=gcp,
                runtime_client=FakeRuntimeClient(),
                registry=FakeRegistry(),
                runner_registry=runner_registry,
            )

            sandbox = await manager.create_sandbox()
            await manager.wait_for_sandbox_startup(sandbox.id)
            stored = await manager.get_sandbox(sandbox.id)
            runner = await runner_registry.get(stored.service_name)

            assert stored.service_name != warm_runner.service_name
            assert runner is not None
            assert runner.pool_kind == "overflow"
            assert len(gcp.created) >= 1
        finally:
            if previous is None:
                os.environ.pop("RUNNER_WARM_POOL_SIZE", None)
            else:
                os.environ["RUNNER_WARM_POOL_SIZE"] = previous

    asyncio.run(scenario())


def test_update_file_only_persists_after_runtime_accepts_change() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeClient()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=runtime,
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        await manager.update_file(sandbox.id, UPDATED_ROUTES_FILE)
        updated_file = await manager.get_file(sandbox.id)
        stored = await manager.get_sandbox(sandbox.id)

        assert updated_file["content"] == UPDATED_ROUTES_FILE
        assert runtime.updated[-1] == (stored.service_url, sandbox.id, UPDATED_ROUTES_FILE)

        runtime.fail_on_update = True
        try:
            await manager.update_file(sandbox.id, DEFAULT_ROUTES_FILE)
        except HTTPException as exc:
            assert exc.status_code == 500
        else:
            raise AssertionError("Expected HTTPException")

        unchanged_file = await manager.get_file(sandbox.id)
        assert unchanged_file["content"] == UPDATED_ROUTES_FILE

    asyncio.run(scenario())


def test_update_file_returns_structured_validation_error_for_syntax_failures() -> None:
    async def scenario() -> None:
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)

        try:
            await manager.update_file(sandbox.id, "from fastapi import APIRouter\nrouter = APIRouter(\n")
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail["kind"] == "syntax_error"
            assert "Invalid Python syntax" in exc.detail["detail"]
            assert exc.detail["line"] == 2
        else:
            raise AssertionError("Expected HTTPException")

    asyncio.run(scenario())


def test_validate_file_surfaces_runner_validation_detail_without_extra_nesting() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeClient()
        runtime.validate_error = HTTPError(
            400,
            {
                "error": "Sandbox validation failed",
                "detail": "name 'st' is not defined",
                "kind": "name_error",
                "line": None,
                "column": None,
            },
        )
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=runtime,
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)

        try:
            await manager.validate_file(sandbox.id, UPDATED_ROUTES_FILE)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail["kind"] == "name_error"
            assert exc.detail["detail"] == "name 'st' is not defined"
        else:
            raise AssertionError("Expected HTTPException")

    asyncio.run(scenario())


def test_reset_reuses_runner_and_restores_default_routes() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeClient()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=runtime,
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        await manager.update_file(sandbox.id, UPDATED_ROUTES_FILE)
        before_reset = await manager.get_sandbox(sandbox.id)
        await manager.reset_sandbox(sandbox.id)
        summary = await manager.get_summary(sandbox.id)
        file_info = await manager.get_file(sandbox.id)

        assert runtime.resets == [(before_reset.service_url, sandbox.id, DEFAULT_ROUTES_FILE)]
        assert file_info["content"] == DEFAULT_ROUTES_FILE
        assert summary["ttl_seconds"] > 0
        assert summary["created_at"] > before_reset.created_at

    asyncio.run(scenario())


def test_cleanup_expired_is_idempotent() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeClient()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=runtime,
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        record = await manager.get_sandbox(sandbox.id)
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await manager._registry.save(record)  # type: ignore[attr-defined]

        result = await manager.cleanup_expired()
        second_result = await manager.cleanup_expired()

        assert result["deleted"] == 1
        assert second_result["deleted"] == 0
        assert runtime.deleted[-1] == (record.service_url, sandbox.id)
        assert await manager._registry.get(sandbox.id) is None  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_cleanup_keeps_runner_alive_while_other_sandboxes_are_still_live() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        gcp = FakeGCPClient()
        runtime = FakeRuntimeClient()
        registry = FakeRegistry()
        runner_registry = FakeRunnerRegistry()
        runner = RunnerRecord(
            service_name="spinbox-runner-shared",
            service_url="https://spinbox-runner-shared.run.app",
            pool_kind="warm",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=2,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(runner)
        gcp.services[runner.service_name] = CloudRunServiceRecord(
            service_name=runner.service_name,
            service_url=runner.service_url,
            create_time=now - timedelta(hours=2),
        )

        expired = SandboxRecord(
            id="expired",
            service_name=runner.service_name,
            service_url=runner.service_url,
            file_content=DEFAULT_ROUTES_FILE,
            routes=[],
            status="active",
            error_detail=None,
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(seconds=1),
        )
        live = SandboxRecord(
            id="live",
            service_name=runner.service_name,
            service_url=runner.service_url,
            file_content=DEFAULT_ROUTES_FILE,
            routes=[],
            status="active",
            error_detail=None,
            created_at=now - timedelta(minutes=30),
            expires_at=now + timedelta(minutes=30),
        )
        await registry.save(expired)
        await registry.save(live)

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=runtime,
            registry=registry,
            runner_registry=runner_registry,
        )

        result = await manager.cleanup_expired()
        stored_runner = await runner_registry.get(runner.service_name)

        assert result["deleted"] == 1
        assert await registry.get("expired") is None
        assert await registry.get("live") is not None
        assert stored_runner is not None
        assert stored_runner.assigned_sandboxes == 1
        assert stored_runner.status == "active"
        assert gcp.deleted == []

    asyncio.run(scenario())


def test_delete_keeps_empty_warm_runner_alive() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        gcp = FakeGCPClient()
        runner_registry = FakeRunnerRegistry()
        warm_runner = RunnerRecord(
            service_name="spinbox-runner-warm-empty",
            service_url="https://spinbox-runner-warm-empty.run.app",
            pool_kind="warm",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=1,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(warm_runner)
        gcp.services[warm_runner.service_name] = CloudRunServiceRecord(
            service_name=warm_runner.service_name,
            service_url=warm_runner.service_url,
            create_time=now - timedelta(hours=2),
        )

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=runner_registry,
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        await manager.delete_sandbox(sandbox.id)
        runner = await runner_registry.get(warm_runner.service_name)

        assert runner is not None
        assert runner.pool_kind == "warm"
        assert runner.assigned_sandboxes == 0
        assert runner.status == "active"
        assert gcp.deleted == []

    asyncio.run(scenario())


def test_reconcile_refills_missing_warm_pool() -> None:
    async def scenario() -> None:
        previous = os.environ.get("RUNNER_WARM_POOL_SIZE")
        os.environ["RUNNER_WARM_POOL_SIZE"] = "10"
        try:
            gcp = FakeGCPClient()
            manager = SandboxManager(
                ttl_seconds=3600,
                gcp_client=gcp,
                runtime_client=FakeRuntimeClient(),
                registry=FakeRegistry(),
                runner_registry=FakeRunnerRegistry(),
            )

            await manager.reconcile_warm_pool()
            runners = await manager._runner_registry.list_all()  # type: ignore[attr-defined]

            assert len(runners) == manager.runner_warm_pool_size
            assert all(runner.pool_kind == "warm" for runner in runners)
            assert all(runner.status == "active" for runner in runners)
            assert all(runner.assigned_sandboxes == 0 for runner in runners)
        finally:
            if previous is None:
                os.environ.pop("RUNNER_WARM_POOL_SIZE", None)
            else:
                os.environ["RUNNER_WARM_POOL_SIZE"] = previous

    asyncio.run(scenario())


def test_reconcile_is_idempotent_when_pool_is_already_full() -> None:
    async def scenario() -> None:
        previous = os.environ.get("RUNNER_WARM_POOL_SIZE")
        os.environ["RUNNER_WARM_POOL_SIZE"] = "10"
        try:
            gcp = FakeGCPClient()
            runner_registry = FakeRunnerRegistry()
            now = datetime.now(UTC)
            for index in range(10):
                runner = RunnerRecord(
                    service_name=f"spinbox-runner-warm-{index}",
                    service_url=f"https://spinbox-runner-warm-{index}.run.app",
                    pool_kind="warm",
                    status="active",
                    max_sandboxes=5,
                    assigned_sandboxes=0,
                    created_at=now,
                    updated_at=now,
                )
                await runner_registry.save(runner)
                gcp.services[runner.service_name] = CloudRunServiceRecord(
                    service_name=runner.service_name,
                    service_url=runner.service_url,
                    create_time=now,
                )

            manager = SandboxManager(
                ttl_seconds=3600,
                gcp_client=gcp,
                runtime_client=FakeRuntimeClient(),
                registry=FakeRegistry(),
                runner_registry=runner_registry,
            )

            await manager.reconcile_warm_pool()

            assert gcp.created == []
            assert len(await runner_registry.list_all()) == 10
        finally:
            if previous is None:
                os.environ.pop("RUNNER_WARM_POOL_SIZE", None)
            else:
                os.environ["RUNNER_WARM_POOL_SIZE"] = previous

    asyncio.run(scenario())


def test_reconcile_trims_excess_idle_warm_runners() -> None:
    async def scenario() -> None:
        previous = os.environ.get("RUNNER_WARM_POOL_SIZE")
        os.environ["RUNNER_WARM_POOL_SIZE"] = "10"
        try:
            gcp = FakeGCPClient()
            runner_registry = FakeRunnerRegistry()
            now = datetime.now(UTC)
            for index in range(11):
                runner = RunnerRecord(
                    service_name=f"spinbox-runner-warm-{index}",
                    service_url=f"https://spinbox-runner-warm-{index}.run.app",
                    pool_kind="warm",
                    status="active",
                    max_sandboxes=5,
                    assigned_sandboxes=0,
                    created_at=now,
                    updated_at=now + timedelta(seconds=index),
                )
                await runner_registry.save(runner)
                gcp.services[runner.service_name] = CloudRunServiceRecord(
                    service_name=runner.service_name,
                    service_url=runner.service_url,
                    create_time=now,
                )

            manager = SandboxManager(
                ttl_seconds=3600,
                gcp_client=gcp,
                runtime_client=FakeRuntimeClient(),
                registry=FakeRegistry(),
                runner_registry=runner_registry,
            )

            await manager.reconcile_warm_pool()

            remaining = await runner_registry.list_all()
            assert len(remaining) == 10
            assert len(gcp.deleted) == 1
            assert gcp.deleted[0] == "spinbox-runner-warm-10"
        finally:
            if previous is None:
                os.environ.pop("RUNNER_WARM_POOL_SIZE", None)
            else:
                os.environ["RUNNER_WARM_POOL_SIZE"] = previous

    asyncio.run(scenario())


def test_cleanup_repairs_stale_runner_count_then_removes_empty_runner() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        gcp = FakeGCPClient()
        runner_registry = FakeRunnerRegistry()
        runner = RunnerRecord(
            service_name="spinbox-runner-stale",
            service_url="https://spinbox-runner-stale.run.app",
            pool_kind="overflow",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=3,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(runner)
        gcp.services[runner.service_name] = CloudRunServiceRecord(
            service_name=runner.service_name,
            service_url=runner.service_url,
            create_time=now - timedelta(hours=2),
        )

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=runner_registry,
        )

        result = await manager.cleanup_expired()

        assert result["deleted"] == 1
        assert await runner_registry.get(runner.service_name) is None
        assert gcp.deleted == [runner.service_name]

    asyncio.run(scenario())


def test_cleanup_removes_runner_registry_entry_when_cloud_run_service_is_missing() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        runner_registry = FakeRunnerRegistry()
        runner = RunnerRecord(
            service_name="spinbox-runner-missing",
            service_url="https://spinbox-runner-missing.run.app",
            pool_kind="overflow",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=1,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(runner)

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=runner_registry,
        )

        result = await manager.cleanup_expired()

        assert result["deleted"] == 1
        assert await runner_registry.get(runner.service_name) is None

    asyncio.run(scenario())


def test_create_sandbox_skips_stale_runner_registry_record() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        gcp = FakeGCPClient()
        runtime = FakeRuntimeClient()
        registry = FakeRegistry()
        runner_registry = FakeRunnerRegistry()
        stale_runner = RunnerRecord(
            service_name="spinbox-runner-stale-registry",
            service_url="https://spinbox-runner-stale-registry.run.app",
            pool_kind="warm",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=0,
            created_at=now,
            updated_at=now,
        )
        live_runner = RunnerRecord(
            service_name="spinbox-runner-live",
            service_url="https://spinbox-runner-live.run.app",
            pool_kind="warm",
            status="active",
            max_sandboxes=5,
            assigned_sandboxes=0,
            created_at=now,
            updated_at=now,
        )
        await runner_registry.save(stale_runner)
        await runner_registry.save(live_runner)
        gcp.services[live_runner.service_name] = CloudRunServiceRecord(
            service_name=live_runner.service_name,
            service_url=live_runner.service_url,
            create_time=now,
        )

        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=runtime,
            registry=registry,
            runner_registry=runner_registry,
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        stored = await manager.get_sandbox(sandbox.id)

        assert stored.service_name == live_runner.service_name
        assert await runner_registry.get(stale_runner.service_name) is None

    asyncio.run(scenario())


def test_get_summary_marks_sandbox_error_when_assigned_runner_is_missing() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        gcp = FakeGCPClient()
        registry = FakeRegistry()
        runner_registry = FakeRunnerRegistry()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=registry,
            runner_registry=runner_registry,
        )

        sandbox = SandboxRecord(
            id="broken-runner",
            service_name="spinbox-runner-missing",
            service_url="https://spinbox-runner-missing.run.app",
            file_content=DEFAULT_ROUTES_FILE,
            routes=[],
            status="active",
            error_detail=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        await registry.save(sandbox)

        summary = await manager.get_summary(sandbox.id)

        assert summary["status"] == "error"
        assert "Assigned runner is missing" in summary["error_detail"]

    asyncio.run(scenario())


def test_proxy_request_uses_runtime_client() -> None:
    async def scenario() -> None:
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=FakeGCPClient(),
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )
        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)
        stored = await manager.get_sandbox(sandbox.id)

        response = await manager.proxy_request(
            sandbox.id,
            method="GET",
            path="/users",
            query_params={},
            headers={},
            raw_body=None,
        )

        assert response.body == {"runner_url": stored.service_url, "sandbox_id": sandbox.id}

    asyncio.run(scenario())


def test_startup_failure_surfaces_in_summary_and_ready_endpoints_fail() -> None:
    async def scenario() -> None:
        gcp = FakeGCPClient()
        gcp.fail_on_create = True
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )

        sandbox = await manager.create_sandbox()
        await manager.wait_for_sandbox_startup(sandbox.id)

        summary = await manager.get_summary(sandbox.id)

        assert summary["status"] == "error"
        assert summary["error_detail"]

        try:
            await manager.get_file(sandbox.id)
        except HTTPException as exc:
            assert exc.status_code == 502
        else:
            raise AssertionError("Expected startup failure to block ready-only endpoints")

    asyncio.run(scenario())


def test_cleanup_deletes_orphaned_cloud_run_runner_without_registry_entry() -> None:
    async def scenario() -> None:
        gcp = FakeGCPClient()
        manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=FakeRuntimeClient(),
            registry=FakeRegistry(),
            runner_registry=FakeRunnerRegistry(),
        )
        orphan = "spinbox-runner-orphaned"
        gcp.services[orphan] = CloudRunServiceRecord(
            service_name=orphan,
            service_url="https://spinbox-runner-orphaned.run.app",
            create_time=datetime.now(UTC) - timedelta(hours=2),
        )

        result = await manager.cleanup_expired()

        assert result["deleted"] == 1
        assert gcp.deleted == [orphan]

    asyncio.run(scenario())


def test_registry_survives_manager_restart() -> None:
    async def scenario() -> None:
        gcp = FakeGCPClient()
        runtime = FakeRuntimeClient()
        registry = FakeRegistry()
        runner_registry = FakeRunnerRegistry()
        first_manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=runtime,
            registry=registry,
            runner_registry=runner_registry,
        )

        sandbox = await first_manager.create_sandbox()
        await first_manager.wait_for_sandbox_startup(sandbox.id)

        restarted_manager = SandboxManager(
            ttl_seconds=3600,
            gcp_client=gcp,
            runtime_client=runtime,
            registry=registry,
            runner_registry=runner_registry,
        )
        summary = await restarted_manager.get_summary(sandbox.id)
        file_info = await restarted_manager.get_file(sandbox.id)
        await restarted_manager.delete_sandbox(sandbox.id)

        assert summary["status"] == "active"
        assert file_info["content"] == DEFAULT_ROUTES_FILE
        assert await registry.get(sandbox.id) is None

    asyncio.run(scenario())
