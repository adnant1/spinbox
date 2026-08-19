from __future__ import annotations

import builtins
import inspect
import json
import re
import types
from dataclasses import dataclass, field
from typing import Any, Callable, get_args, get_origin


SAFE_BUILTINS: dict[str, Any] = {
    # Keep the execution surface intentionally small so sandbox scripts can
    # express route logic without having unrestricted access to Python internals.
    "__import__": __import__,
    "__build_class__": builtins.__build_class__,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "next": next,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "print": print,
    "zip": zip,
    "object": object,
    "Exception": Exception,
    "ValueError": ValueError,
    "KeyError": KeyError,
}


class SandboxExecutionError(Exception):
    """Raised when sandbox code cannot be compiled or executed."""


class HTTPException(Exception):
    """Small FastAPI-style exception surface exposed to sandbox code."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class HTTPError(Exception):
    """Carries an HTTP-style status code and payload through sandbox execution."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


@dataclass(slots=True)
class ResponseSpec:
    """Normalized response returned by sandbox handlers before FastAPI serialization."""

    body: Any
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class CompiledSandbox:
    """Compiled route table plus the backing module globals."""

    routes: list["RouteDefinition"]
    globals_dict: dict[str, Any]


@dataclass(slots=True)
class RequestContext:
    """Minimal request object passed into dynamically executed route handlers."""

    sandbox_id: str
    method: str
    path: str
    query_params: dict[str, str]
    headers: dict[str, str]
    raw_body: str | None
    json_body: Any
    path_params: dict[str, str]

    def json(self) -> Any:
        """Return the parsed JSON body when the request payload is valid JSON."""
        return self.json_body

    @property
    def body(self) -> Any:
        """Expose JSON bodies as objects and fall back to raw text otherwise."""
        if self.json_body is not None:
            return self.json_body
        return self.raw_body


@dataclass(slots=True)
class RouteDefinition:
    """Compiled representation of a sandbox route handler."""

    method: str
    path: str
    regex: re.Pattern[str]
    param_names: list[str]
    handler: Callable[..., Any]
    default_status_code: int = 200

    def matches(self, method: str, path: str) -> dict[str, str] | None:
        """Return extracted path params when this route matches the request."""
        if self.method not in {method.upper(), "ANY"}:
            return None

        match = self.regex.fullmatch(path)
        if match is None:
            return None
        return {name: value for name, value in match.groupdict().items() if value is not None}


def normalize_path(path: str | None) -> str:
    """Normalize user-provided paths into a canonical slash-prefixed form."""
    if not path:
        return "/"

    normalized = path if path.startswith("/") else f"/{path}"
    if len(normalized) > 1 and normalized.endswith("/"):
        return normalized.rstrip("/")
    return normalized


def compile_route_pattern(path: str) -> tuple[re.Pattern[str], list[str]]:
    """Convert FastAPI-style route syntax into a regex matcher and param list."""
    normalized = normalize_path(path)
    if normalized == "/":
        return re.compile(r"^/$"), []

    param_names: list[str] = []
    parts = []
    for segment in normalized.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            # Route params use FastAPI-style `{name}` syntax and become named
            # regex groups so the dispatcher can inject them into handlers later.
            name = segment[1:-1].strip()
            if not name:
                raise SandboxExecutionError("Route parameter names cannot be empty.")
            param_names.append(name)
            parts.append(f"(?P<{name}>[^/]+)")
        else:
            parts.append(re.escape(segment))

    pattern = "^/" + "/".join(parts) + "$"
    return re.compile(pattern), param_names


def normalize_handler_result(result: Any) -> ResponseSpec:
    """Coerce handler return values into a consistent response container."""
    if isinstance(result, ResponseSpec):
        return result

    if isinstance(result, tuple):
        if len(result) == 2:
            body, status_code = result
            return ResponseSpec(body=body, status_code=int(status_code))
        if len(result) == 3:
            body, status_code, headers = result
            return ResponseSpec(
                body=body,
                status_code=int(status_code),
                headers=dict(headers or {}),
            )
        raise SandboxExecutionError("Handler tuples must be (body, status) or (body, status, headers).")

    return ResponseSpec(body=result, status_code=200)


class BaseModel:
    """Minimal Pydantic-style model used by sandbox starter templates."""

    __fields__: dict[str, tuple[Any, Any]] = {}
    __sandbox_globals__: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        raw_annotations = dict(getattr(cls, "__annotations__", {}))
        fields: dict[str, tuple[Any, Any]] = {}
        sandbox_globals = dict(BaseModel.__sandbox_globals__)
        sandbox_globals[cls.__name__] = cls
        for name, annotation in raw_annotations.items():
            if isinstance(annotation, str):
                annotation = eval(annotation, sandbox_globals, sandbox_globals)
            default = getattr(cls, name, inspect.Signature.empty)
            fields[name] = (annotation, default)
        cls.__fields__ = fields

    def __init__(self, **data: Any) -> None:
        for name, (annotation, default) in self.__fields__.items():
            if name in data:
                value = data[name]
            elif default is not inspect.Signature.empty:
                value = default
            elif _annotation_allows_none(annotation):
                value = None
            else:
                raise ValueError(f"Field '{name}' is required")

            setattr(self, name, _coerce_value(value, annotation))

    def dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__fields__}

    def model_dump(self) -> dict[str, Any]:
        return self.dict()


class FastAPI:
    """Tiny app object that exposes route decorators like FastAPI."""

    def __init__(self, register: Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]) -> None:
        self._register = register

    def get(self, path: str, *, status_code: int = 200) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._register("GET", path, status_code=status_code)

    def post(self, path: str, *, status_code: int = 200) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._register("POST", path, status_code=status_code)

    def put(self, path: str, *, status_code: int = 200) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._register("PUT", path, status_code=status_code)

    def delete(self, path: str, *, status_code: int = 200) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._register("DELETE", path, status_code=status_code)

    def patch(self, path: str, *, status_code: int = 200) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._register("PATCH", path, status_code=status_code)


def _annotation_allows_none(annotation: Any) -> bool:
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    if origin is None:
        return annotation is type(None)
    return type(None) in get_args(annotation)


def _coerce_value(value: Any, annotation: Any) -> Any:
    if annotation in {inspect.Signature.empty, Any}:
        return value
    if value is None:
        return None

    origin = get_origin(annotation)
    if origin is None:
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            if isinstance(value, annotation):
                return value
            if not isinstance(value, dict):
                raise ValueError(f"Expected object payload for {annotation.__name__}")
            return annotation(**value)
        if annotation in {str, int, float, bool}:
            return annotation(value)
        return value

    args = [option for option in get_args(annotation) if option is not type(None)]
    if origin in {list, tuple} and isinstance(value, (list, tuple)) and args:
        inner = args[0]
        return origin(_coerce_value(item, inner) for item in value)
    if origin is dict:
        return value
    if args:
        for option in args:
            try:
                return _coerce_value(value, option)
            except (TypeError, ValueError):
                continue
    return value


class SandboxCompiler:
    """Compile editable sandbox source code into executable route definitions."""

    def compile(
        self,
        content: str,
        sandbox_data: dict[str, Any],
        runtime_state: dict[str, Any] | None = None,
    ) -> CompiledSandbox:
        """Execute a sandbox script and collect the routes it registers."""
        routes: list[RouteDefinition] = []

        def register(
            method: str,
            path: str,
            *,
            status_code: int = 200,
        ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            """Capture handlers declared by decorators such as `@get` and `@post`."""
            def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
                regex, param_names = compile_route_pattern(path)
                routes.append(
                    RouteDefinition(
                        method=method.upper(),
                        path=normalize_path(path),
                        regex=regex,
                        param_names=param_names,
                        handler=handler,
                        default_status_code=status_code,
                    )
                )
                return handler

            return decorator

        fastapi_module = types.SimpleNamespace(FastAPI=None, HTTPException=HTTPException)
        pydantic_module = types.SimpleNamespace(BaseModel=BaseModel)

        def sandbox_import(
            name: str,
            globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            if level != 0:
                raise ImportError("Relative imports are not supported in the sandbox")
            if name == "fastapi":
                return fastapi_module
            if name == "pydantic":
                return pydantic_module
            if name == "typing":
                return __import__(name, globals, locals, fromlist, level)
            raise ImportError(f"Import '{name}' is not available in the sandbox")

        # The executed script receives a tiny API surface that mirrors the MVP's
        # editable `routes.py` experience rather than a real FastAPI runtime.
        safe_builtins = dict(SAFE_BUILTINS)
        safe_builtins["__import__"] = sandbox_import
        globals_dict: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
            "db": sandbox_data,
            "route": lambda method, path, status_code=200: register(method, path, status_code=status_code),
            "get": lambda path, status_code=200: register("GET", path, status_code=status_code),
            "post": lambda path, status_code=200: register("POST", path, status_code=status_code),
            "put": lambda path, status_code=200: register("PUT", path, status_code=status_code),
            "delete": lambda path, status_code=200: register("DELETE", path, status_code=status_code),
            "patch": lambda path, status_code=200: register("PATCH", path, status_code=status_code),
            "options": lambda path, status_code=200: register("OPTIONS", path, status_code=status_code),
            "any_route": lambda path, status_code=200: register("ANY", path, status_code=status_code),
            "Response": ResponseSpec,
            "response": lambda body, status_code=200, headers=None: ResponseSpec(
                body=body,
                status_code=status_code,
                headers=dict(headers or {}),
            ),
            "HTTPError": HTTPError,
            "HTTPException": HTTPException,
            "BaseModel": BaseModel,
            "json": json,
        }
        globals_dict.update(runtime_state or {})
        globals_dict["FastAPI"] = lambda: FastAPI(register)
        BaseModel.__sandbox_globals__ = globals_dict
        fastapi_module.FastAPI = globals_dict["FastAPI"]

        try:
            exec(content, globals_dict, globals_dict)
            current_db = globals_dict.get("db")
            if isinstance(current_db, dict) and current_db is not sandbox_data:
                sandbox_data.clear()
                sandbox_data.update(current_db)
                globals_dict["db"] = sandbox_data
        except HTTPError:
            raise
        except HTTPException as exc:
            raise SandboxExecutionError(str(exc.detail)) from exc
        except Exception as exc:  # noqa: BLE001
            raise SandboxExecutionError(str(exc)) from exc

        return CompiledSandbox(routes=routes, globals_dict=globals_dict)


class SandboxDispatcher:
    """Resolve requests against compiled routes and execute the matching handler."""

    async def dispatch(
        self,
        *,
        sandbox_id: str,
        routes: list[RouteDefinition],
        method: str,
        path: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        raw_body: str | None,
    ) -> ResponseSpec:
        """Execute the matching route handler and normalize its response."""
        normalized_path = normalize_path(path)
        route, path_params = self._resolve_route(routes, method, normalized_path)
        if route is None:
            raise HTTPError(
                404,
                {
                    "error": "Route not found",
                    "detail": f"No handler registered for {method.upper()} {normalized_path}",
                },
            )

        json_body = None
        if raw_body:
            try:
                json_body = json.loads(raw_body)
            except json.JSONDecodeError:
                # Plain-text payloads are still valid for the tester, so only
                # promote the body to JSON when parsing succeeds.
                json_body = None

        request = RequestContext(
            sandbox_id=sandbox_id,
            method=method.upper(),
            path=normalized_path,
            query_params=query_params,
            headers=headers,
            raw_body=raw_body,
            json_body=json_body,
            path_params=path_params,
        )

        try:
            result = route.handler(**self._build_arguments(route.handler, request, path_params))
            if inspect.isawaitable(result):
                result = await result
        except HTTPException as exc:
            raise HTTPError(exc.status_code, exc.detail) from exc
        except HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPError(
                500,
                {
                    "error": "Sandbox execution failed",
                    "detail": str(exc),
                },
            ) from exc

        response = normalize_handler_result(result)
        if response.status_code == 200 and route.default_status_code != 200:
            response.status_code = route.default_status_code
        return response

    def _resolve_route(
        self,
        routes: list[RouteDefinition],
        method: str,
        path: str,
    ) -> tuple[RouteDefinition | None, dict[str, str]]:
        """Find the first route whose method and path pattern match the request."""
        for route in routes:
            path_params = route.matches(method, path)
            if path_params is not None:
                return route, path_params
        return None, {}

    def _build_arguments(
        self,
        handler: Callable[..., Any],
        request: RequestContext,
        path_params: dict[str, str],
    ) -> dict[str, Any]:
        """Map request data into the handler signature expected by sandbox code."""
        signature = inspect.signature(handler)
        resolved_annotations = inspect.get_annotations(handler, eval_str=True)
        arguments: dict[str, Any] = {}

        for name, parameter in signature.parameters.items():
            annotation = resolved_annotations.get(name, parameter.annotation)
            # Handlers can opt into a minimal request object, the parsed body,
            # or FastAPI-style path parameters by name.
            if name == "request":
                arguments[name] = request
                continue
            if name == "body":
                arguments[name] = request.body
                continue
            if name in path_params:
                arguments[name] = _coerce_value(path_params[name], annotation)
                continue
            if (
                request.json_body is not None
                and annotation is not inspect.Signature.empty
                and inspect.isclass(annotation)
                and issubclass(annotation, BaseModel)
            ):
                arguments[name] = _coerce_value(request.json_body, annotation)
                continue
            if parameter.default is inspect.Signature.empty:
                raise HTTPError(
                    500,
                    {
                        "error": "Invalid handler signature",
                        "detail": f"Parameter '{name}' cannot be resolved for route {request.method} {request.path}",
                    },
                )

        return arguments
