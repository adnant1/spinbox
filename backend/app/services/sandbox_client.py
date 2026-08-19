from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import google.auth
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
import httpx


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class HTTPError(Exception):
    """Carries an HTTP-style status code and payload back to FastAPI handlers."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


@dataclass(slots=True)
class ResponseSpec:
    """Normalized proxied sandbox response returned to the FastAPI layer."""

    body: Any
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class SandboxRuntimeClient:
    """Talk to deployed multi-tenant runner Cloud Run services."""

    def __init__(self, *, require_auth: bool = True, timeout_seconds: float = 60.0) -> None:
        self.require_auth = require_auth
        self.timeout_seconds = timeout_seconds
        self._request = Request()
        self._access_credentials: Credentials | None = None

    async def create_sandbox(self, runner_url: str, sandbox_id: str, code: str) -> None:
        try:
            headers = await self._auth_headers(runner_url)
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox create: {exc}") from exc
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{runner_url.rstrip('/')}/internal/sandboxes",
                json={"sandbox_id": sandbox_id, "code": code},
                headers=headers,
            )
        if response.status_code >= 400:
            raise HTTPError(response.status_code, _read_error_payload(response))

    async def update_routes(self, runner_url: str, sandbox_id: str, code: str) -> None:
        try:
            headers = await self._auth_headers(runner_url)
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox update: {exc}") from exc
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.put(
                f"{runner_url.rstrip('/')}/internal/sandboxes/{sandbox_id}/file",
                json={"code": code},
                headers=headers,
            )
        if response.status_code >= 400:
            raise HTTPError(response.status_code, _read_error_payload(response))

    async def validate_routes(self, runner_url: str, sandbox_id: str, code: str) -> None:
        try:
            headers = await self._auth_headers(runner_url)
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox validate: {exc}") from exc
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{runner_url.rstrip('/')}/internal/sandboxes/{sandbox_id}/validate",
                json={"code": code},
                headers=headers,
            )
        if response.status_code >= 400:
            raise HTTPError(response.status_code, _read_error_payload(response))

    async def reset_sandbox(self, runner_url: str, sandbox_id: str, code: str) -> None:
        try:
            headers = await self._auth_headers(runner_url)
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox reset: {exc}") from exc
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{runner_url.rstrip('/')}/internal/sandboxes/{sandbox_id}/reset",
                json={"code": code},
                headers=headers,
            )
        if response.status_code >= 400:
            raise HTTPError(response.status_code, _read_error_payload(response))

    async def delete_sandbox(self, runner_url: str, sandbox_id: str) -> None:
        try:
            headers = await self._auth_headers(runner_url)
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox delete: {exc}") from exc
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.delete(
                f"{runner_url.rstrip('/')}/internal/sandboxes/{sandbox_id}",
                headers=headers,
            )
        if response.status_code == 404:
            return
        if response.status_code >= 400:
            raise HTTPError(response.status_code, _read_error_payload(response))

    async def proxy_request(
        self,
        runner_url: str,
        sandbox_id: str,
        *,
        method: str,
        path: str,
        query_params: dict[str, str],
        headers: dict[str, str],
        raw_body: str | None,
    ) -> ResponseSpec:
        outbound_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        try:
            outbound_headers.update(await self._auth_headers(runner_url))
        except DefaultCredentialsError as exc:
            raise HTTPError(502, f"Could not authorize sandbox request: {exc}") from exc

        normalized_path = path if path.startswith("/") else f"/{path}" if path else "/"
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.request(
                method=method,
                url=f"{runner_url.rstrip('/')}/internal/sandboxes/{sandbox_id}{normalized_path}",
                params=query_params,
                content=raw_body.encode("utf-8") if raw_body is not None else None,
                headers=outbound_headers,
            )

        body: Any
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = response.json()
            except ValueError:
                body = response.text
        else:
            body = response.content

        return ResponseSpec(
            body=body,
            status_code=response.status_code,
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            },
        )

    async def _auth_headers(self, audience: str) -> dict[str, str]:
        if not self.require_auth:
            return {}
        try:
            token = await asyncio.to_thread(id_token.fetch_id_token, self._request, audience)
            return {"Authorization": f"Bearer {token}"}
        except DefaultCredentialsError:
            cli_token = await asyncio.to_thread(self._gcloud_identity_token, audience)
            if cli_token:
                return {"Authorization": f"Bearer {cli_token}"}
            # Local ADC from `gcloud auth application-default login` typically
            # yields user credentials, which can refresh an OAuth access token
            # but cannot mint a service-style ID token. Cloud Run accepts the
            # bearer access token as long as the principal has Invoker access.
            access_token = await asyncio.to_thread(self._access_token)
            return {"Authorization": f"Bearer {access_token}"}

    def _access_token(self) -> str:
        credentials = self._get_access_credentials()
        credentials.refresh(self._request)
        if not credentials.token:
            raise DefaultCredentialsError("Application Default Credentials could not refresh an access token.")
        return credentials.token

    def _get_access_credentials(self) -> Credentials:
        if self._access_credentials is None:
            credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
            self._access_credentials = credentials
        return self._access_credentials

    def _gcloud_identity_token(self, audience: str) -> str | None:
        command = shutil.which("gcloud.cmd") or shutil.which("gcloud")
        if not command:
            return None

        completed = subprocess.run(
            [command, "auth", "print-identity-token", f"--audiences={audience}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None

        token = completed.stdout.strip()
        return token or None


def _read_error_payload(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                return payload["detail"]
            return payload
        except ValueError:
            return response.text
    return response.text
