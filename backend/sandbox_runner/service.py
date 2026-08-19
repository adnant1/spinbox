from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRouter


DATABASE_FILE_NAME = "sandbox.db"
ROUTES_FILE_NAME = "routes.py"


DATABASE_TEMPLATE = """from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
{pool_import}

DATABASE_URL = "{database_url}"
engine = create_engine(DATABASE_URL, connect_args={{"check_same_thread": False}}{pool_args})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""


@dataclass(slots=True)
class LoadedSandbox:
    sandbox_id: str
    root_dir: Path
    routes_path: Path
    database_path: Path
    app: FastAPI


@dataclass(slots=True)
class SandboxValidationError(Exception):
    """Structured user-code validation failure raised while loading a sandbox."""

    message: str
    kind: str = "validation_error"
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        return self.message

    def to_detail(self) -> dict[str, Any]:
        return {
            "error": "Sandbox validation failed",
            "detail": self.message,
            "kind": self.kind,
            "line": self.line,
            "column": self.column,
        }


class MultiTenantSandboxRunner:
    """Host multiple isolated FastAPI sandboxes inside one runner process."""

    def __init__(self, root_dir: Path, *, use_in_memory_db: bool = False) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.use_in_memory_db = use_in_memory_db
        self._sandboxes: dict[str, LoadedSandbox] = {}
        self._lock = asyncio.Lock()

    async def create_sandbox(self, sandbox_id: str, code: str) -> None:
        async with self._lock:
            if sandbox_id in self._sandboxes:
                raise HTTPException(status_code=409, detail="Sandbox already exists.")
            sandbox = await asyncio.to_thread(self._materialize_sandbox, sandbox_id, code, True)
            self._sandboxes[sandbox_id] = sandbox

    async def update_file(self, sandbox_id: str, code: str) -> None:
        async with self._lock:
            current = self._require_sandbox(sandbox_id)
            sandbox = await asyncio.to_thread(self._materialize_sandbox, sandbox_id, code, False)
            sandbox.database_path = current.database_path
            self._sandboxes[sandbox_id] = sandbox

    async def reset_sandbox(self, sandbox_id: str, code: str) -> None:
        async with self._lock:
            self._require_sandbox(sandbox_id)
            sandbox = await asyncio.to_thread(self._materialize_sandbox, sandbox_id, code, True)
            self._sandboxes[sandbox_id] = sandbox

    async def validate_file(self, sandbox_id: str, code: str) -> None:
        async with self._lock:
            self._require_sandbox(sandbox_id)
            await asyncio.to_thread(self._validate_candidate_sandbox, sandbox_id, code)

    async def delete_sandbox(self, sandbox_id: str) -> None:
        async with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            if sandbox is None:
                raise HTTPException(status_code=404, detail="Sandbox not found.")
            await asyncio.to_thread(shutil.rmtree, sandbox.root_dir, True)

    async def proxy_request(
        self,
        sandbox_id: str,
        *,
        method: str,
        path: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], Any]:
        async with self._lock:
            sandbox = self._require_sandbox(sandbox_id)
            app = sandbox.app

        normalized_path = path if path.startswith("/") else f"/{path}" if path else "/"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sandbox") as client:
            response = await client.request(
                method=method,
                url=normalized_path,
                params=query_params,
                headers=headers,
                content=body,
            )

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload: Any = response.json()
        else:
            payload = response.content
        response_headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
        return response.status_code, response_headers, payload

    def _materialize_sandbox(self, sandbox_id: str, code: str, reset_db: bool) -> LoadedSandbox:
        root_dir = (self.root_dir / sandbox_id).resolve()
        if reset_db and root_dir.exists():
            shutil.rmtree(root_dir, ignore_errors=True)
        root_dir.mkdir(parents=True, exist_ok=True)

        routes_path = root_dir / ROUTES_FILE_NAME
        database_path = root_dir / DATABASE_FILE_NAME
        database_module_path = root_dir / "database.py"

        routes_path.write_text(code, encoding="utf-8")
        database_url = "sqlite://" if self.use_in_memory_db else f"sqlite:///{database_path.resolve().as_posix()}"
        pool_import = "from sqlalchemy.pool import StaticPool" if self.use_in_memory_db else ""
        pool_args = ", poolclass=StaticPool" if self.use_in_memory_db else ""
        database_module_path.write_text(
            DATABASE_TEMPLATE.format(database_url=database_url, pool_import=pool_import, pool_args=pool_args),
            encoding="utf-8",
        )

        app = self._load_fastapi_app(sandbox_id, root_dir, database_module_path, routes_path)
        return LoadedSandbox(
            sandbox_id=sandbox_id,
            root_dir=root_dir,
            routes_path=routes_path,
            database_path=database_path,
            app=app,
        )

    def _load_fastapi_app(
        self,
        sandbox_id: str,
        root_dir: Path,
        database_module_path: Path,
        routes_path: Path,
    ) -> FastAPI:
        package_name = f"spinbox_runner_{sandbox_id}"
        package = ModuleType(package_name)
        package.__path__ = [str(root_dir)]  # type: ignore[attr-defined]
        sys.modules[package_name] = package

        database_module = self._load_module(f"{package_name}.database", database_module_path)
        previous_database = sys.modules.get("database")
        sys.modules["database"] = database_module
        try:
            routes_module = self._load_module(f"{package_name}.routes", routes_path)
        finally:
            if previous_database is None:
                sys.modules.pop("database", None)
            else:
                sys.modules["database"] = previous_database

        router = getattr(routes_module, "router", None)
        if not isinstance(router, APIRouter):
            raise HTTPException(status_code=400, detail="Sandbox routes.py must define `router = APIRouter()`.")

        database_module.Base.metadata.create_all(bind=database_module.engine)
        app = FastAPI()
        app.include_router(router)
        return app

    def _validate_candidate_sandbox(self, sandbox_id: str, code: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"spinbox-validate-{sandbox_id}-") as temp_dir:
            root_dir = Path(temp_dir)
            routes_path = root_dir / ROUTES_FILE_NAME
            database_path = root_dir / DATABASE_FILE_NAME
            database_module_path = root_dir / "database.py"

            routes_path.write_text(code, encoding="utf-8")
            database_url = "sqlite://" if self.use_in_memory_db else f"sqlite:///{database_path.resolve().as_posix()}"
            pool_import = "from sqlalchemy.pool import StaticPool" if self.use_in_memory_db else ""
            pool_args = ", poolclass=StaticPool" if self.use_in_memory_db else ""
            database_module_path.write_text(
                DATABASE_TEMPLATE.format(database_url=database_url, pool_import=pool_import, pool_args=pool_args),
                encoding="utf-8",
            )

            self._load_fastapi_app(f"{sandbox_id}_validate", root_dir, database_module_path, routes_path)

    @staticmethod
    def _load_module(module_name: str, path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=500, detail=f"Could not load module from {path}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except SyntaxError as exc:
            raise SandboxValidationError(
                f"Invalid Python syntax: {exc.msg}",
                kind="syntax_error",
                line=exc.lineno,
                column=exc.offset,
            ) from exc
        except NameError as exc:
            raise SandboxValidationError(str(exc), kind="name_error") from exc
        except ImportError as exc:
            raise SandboxValidationError(str(exc), kind="import_error") from exc
        except TypeError as exc:
            raise SandboxValidationError(str(exc), kind="type_error") from exc
        except ValueError as exc:
            raise SandboxValidationError(str(exc), kind="value_error") from exc
        return module

    def _require_sandbox(self, sandbox_id: str) -> LoadedSandbox:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=404, detail="Sandbox not found.")
        return sandbox
