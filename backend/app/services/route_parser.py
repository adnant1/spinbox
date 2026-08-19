from __future__ import annotations

import ast
from dataclasses import dataclass


class RouteValidationError(Exception):
    """Raised when user-provided routes.py does not meet Spinbox constraints."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "validation_error",
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.line = line
        self.column = column


@dataclass(slots=True)
class RouteDefinition:
    """Tester-visible metadata extracted from a sandbox routes.py file."""

    method: str
    path: str
    param_names: list[str]


ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def parse_routes_file(content: str) -> list[RouteDefinition]:
    """Validate routes.py and extract router-decorated endpoint metadata."""
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        raise RouteValidationError(
            f"Invalid Python syntax: {exc.msg}",
            kind="syntax_error",
            line=exc.lineno,
            column=exc.offset,
        ) from exc

    has_router_assignment = False
    routes: list[RouteDefinition] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_router_assignment(node):
            has_router_assignment = True
        elif isinstance(node, ast.Call) and _is_fastapi_instantiation(node):
            raise RouteValidationError("routes.py must not create a FastAPI app; use `router = APIRouter()` instead.")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            routes.extend(_extract_routes(node))

    if not has_router_assignment:
        raise RouteValidationError("routes.py must define `router = APIRouter()`.")

    return routes


def _is_router_assignment(node: ast.Assign) -> bool:
    if len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name) or target.id != "router":
        return False
    value = node.value
    if not isinstance(value, ast.Call):
        return False
    return _call_name(value.func) == "APIRouter"


def _is_fastapi_instantiation(node: ast.Call) -> bool:
    return _call_name(node.func) == "FastAPI"


def _extract_routes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[RouteDefinition]:
    routes: list[RouteDefinition] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
            continue

        method = decorator.func.attr.upper()
        if method not in ALLOWED_METHODS:
            continue
        if not decorator.args:
            raise RouteValidationError(f"`@router.{decorator.func.attr}` must include a path string.")

        first_arg = decorator.args[0]
        if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
            raise RouteValidationError(f"`@router.{decorator.func.attr}` path must be a string literal.")

        path = _normalize_path(first_arg.value)
        routes.append(
            RouteDefinition(
                method=method,
                path=path,
                param_names=_extract_path_params(path),
            )
        )
    return routes


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    normalized = path if path.startswith("/") else f"/{path}"
    if len(normalized) > 1 and normalized.endswith("/"):
        return normalized.rstrip("/")
    return normalized


def _extract_path_params(path: str) -> list[str]:
    params: list[str] = []
    for segment in path.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            params.append(segment[1:-1].strip())
    return [param for param in params if param]
