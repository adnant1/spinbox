from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from fastapi.testclient import TestClient

from sandbox_runner.main import app
from sandbox_runner.service import MultiTenantSandboxRunner


UPDATED_ROUTES_FILE = """
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from database import Base, get_db

router = APIRouter()

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

class User(BaseModel):
    name: str

@router.post("/users", status_code=201)
def create_user(user: User, db: Session = Depends(get_db)):
    row = UserDB(name=user.name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

@router.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(UserDB).all()
    return {"count": len(users), "users": users}
"""


def test_runner_isolates_sandbox_state(monkeypatch) -> None:
    temp_dir = Path("tests") / f"tmp-runner-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setattr("sandbox_runner.main.runner", MultiTenantSandboxRunner(temp_dir, use_in_memory_db=True))
        client = TestClient(app)

        create_one = client.post("/internal/sandboxes", json={"sandbox_id": "one", "code": UPDATED_ROUTES_FILE})
        create_two = client.post("/internal/sandboxes", json={"sandbox_id": "two", "code": UPDATED_ROUTES_FILE})
        assert create_one.status_code == 200
        assert create_two.status_code == 200

        response = client.post("/internal/sandboxes/one/users", json={"name": "Ada"})
        assert response.status_code == 201

        users_one = client.get("/internal/sandboxes/one/users")
        users_two = client.get("/internal/sandboxes/two/users")

        assert users_one.json()["count"] == 1
        assert users_two.json()["count"] == 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_runner_reset_recreates_database(monkeypatch) -> None:
    temp_dir = Path("tests") / f"tmp-runner-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setattr("sandbox_runner.main.runner", MultiTenantSandboxRunner(temp_dir, use_in_memory_db=True))
        client = TestClient(app)

        client.post("/internal/sandboxes", json={"sandbox_id": "reset-me", "code": UPDATED_ROUTES_FILE})
        client.post("/internal/sandboxes/reset-me/users", json={"name": "Ada"})

        reset = client.post(
            "/internal/sandboxes/reset-me/reset",
            json={"code": UPDATED_ROUTES_FILE},
        )
        users = client.get("/internal/sandboxes/reset-me/users")

        assert reset.status_code == 200
        assert users.json()["count"] == 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_runner_update_surfaces_structured_validation_errors(monkeypatch) -> None:
    temp_dir = Path("tests") / f"tmp-runner-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    invalid_routes = UPDATED_ROUTES_FILE.replace("name: str", "name: st")
    try:
        monkeypatch.setattr("sandbox_runner.main.runner", MultiTenantSandboxRunner(temp_dir, use_in_memory_db=True))
        client = TestClient(app)

        create = client.post("/internal/sandboxes", json={"sandbox_id": "broken", "code": UPDATED_ROUTES_FILE})
        update = client.put("/internal/sandboxes/broken/file", json={"code": invalid_routes})

        assert create.status_code == 200
        assert update.status_code == 400
        assert update.json()["detail"]["kind"] == "name_error"
        assert "st" in update.json()["detail"]["detail"]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
