from app.services.route_parser import RouteValidationError, parse_routes_file
from app.services.sandbox_manager import DEFAULT_ROUTES_FILE


def test_parse_routes_file_extracts_tester_routes() -> None:
    routes = parse_routes_file(DEFAULT_ROUTES_FILE)

    assert [(route.method, route.path) for route in routes] == [
        ("GET", "/"),
        ("GET", "/users"),
        ("POST", "/users"),
        ("GET", "/users/{user_id}"),
        ("DELETE", "/users/{user_id}"),
    ]
    assert routes[-1].param_names == ["user_id"]


def test_parse_routes_file_rejects_fastapi_app_instantiation() -> None:
    content = """
from fastapi import FastAPI, APIRouter

router = APIRouter()
app = FastAPI()
"""

    try:
        parse_routes_file(content)
    except RouteValidationError as exc:
        assert "must not create a FastAPI app" in str(exc)
    else:
        raise AssertionError("Expected RouteValidationError")


def test_parse_routes_file_requires_router_assignment() -> None:
    content = """
from fastapi import APIRouter

api = APIRouter()
"""

    try:
        parse_routes_file(content)
    except RouteValidationError as exc:
        assert "router = APIRouter" in str(exc)
    else:
        raise AssertionError("Expected RouteValidationError")
