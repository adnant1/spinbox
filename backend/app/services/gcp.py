from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import google.auth
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
import httpx


DEFAULT_REGION = "us-central1"
DEFAULT_REPOSITORY = "spinbox-repo"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
RUN_API_BASE = "https://run.googleapis.com/v2"
RUNNER_SERVICE_PREFIX = "spinbox-runner-"


class GCPConfigurationError(RuntimeError):
    """Raised when GCP configuration is incomplete or invalid."""


class GCPOperationError(RuntimeError):
    """Raised when a Cloud Run operation fails."""


@dataclass(slots=True)
class CloudRunService:
    """Minimal Cloud Run metadata the control plane needs to persist."""

    service_name: str
    service_url: str


@dataclass(slots=True)
class CloudRunServiceRecord:
    """Cloud Run service metadata used during cleanup reconciliation."""

    service_name: str
    service_url: str
    create_time: datetime | None


class GCPClient:
    """Manage sandbox Cloud Run services through the Cloud Run v2 REST API."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        region: str | None = None,
        repository_name: str | None = None,
        image_uri: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.region = region or os.getenv("GCP_REGION", DEFAULT_REGION)
        self.repository_name = repository_name or os.getenv("ARTIFACT_REPOSITORY", DEFAULT_REPOSITORY)
        self.image_uri = image_uri or os.getenv("IMAGE_URI")
        self.timeout_seconds = timeout_seconds

        if not self.project_id:
            raise GCPConfigurationError("GCP_PROJECT_ID must be configured.")
        if not self.region:
            raise GCPConfigurationError("GCP_REGION must be configured.")
        if not self.image_uri:
            raise GCPConfigurationError("IMAGE_URI must be configured.")

        self._credentials: Credentials | None = None

    async def create_runner(self, runner_id: str) -> CloudRunService:
        """Deploy a fresh Cloud Run runner service and return its URL."""
        service_name = self._service_name_for_id(runner_id)
        parent = f"projects/{self.project_id}/locations/{self.region}"
        url = f"{RUN_API_BASE}/{parent}/services?serviceId={service_name}"
        payload = {
            "template": {
                "containers": [{"image": self.image_uri}],
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, headers=await self._api_headers(), json=payload)
            self._raise_for_status(response, "create Cloud Run service")
            operation = response.json()
            await self._wait_for_operation(client, operation["name"])
            service = await self._get_service(client, service_name)

        service_url = service.get("uri")
        if not service_url:
            raise GCPOperationError(f"Cloud Run service {service_name} did not return a URL.")
        return CloudRunService(service_name=service_name, service_url=service_url)

    async def delete_runner(self, service_name: str) -> None:
        """Delete a runner Cloud Run service. Missing services are treated as already gone."""
        service_path = self._service_path(service_name)
        url = f"{RUN_API_BASE}/{service_path}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.delete(url, headers=await self._api_headers())
            if response.status_code == 404:
                return
            self._raise_for_status(response, "delete Cloud Run service")
            operation = response.json()
            await self._wait_for_operation(client, operation["name"])

    async def list_runners(self) -> list[CloudRunServiceRecord]:
        """List runner Cloud Run services so cleanup can reconcile orphaned resources."""
        parent = f"projects/{self.project_id}/locations/{self.region}"
        url = f"{RUN_API_BASE}/{parent}/services"
        runner_services: list[CloudRunServiceRecord] = []
        page_token: str | None = None

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while True:
                params: dict[str, str] = {}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(url, headers=await self._api_headers(), params=params)
                self._raise_for_status(response, "list Cloud Run services")
                payload = response.json()

                for service in payload.get("services", []):
                    name = service.get("name", "").split("/")[-1]
                    if not name.startswith(RUNNER_SERVICE_PREFIX):
                        continue
                    runner_services.append(
                        CloudRunServiceRecord(
                            service_name=name,
                            service_url=service.get("uri", ""),
                            create_time=_parse_google_timestamp(service.get("createTime")),
                        )
                    )

                page_token = payload.get("nextPageToken")
                if not page_token:
                    break

        return runner_services

    async def get_runner(self, service_name: str) -> CloudRunServiceRecord | None:
        """Fetch a single runner service when validating an assigned sandbox runner."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{RUN_API_BASE}/{self._service_path(service_name)}",
                headers=await self._api_headers(),
            )
            if response.status_code == 404:
                return None
            self._raise_for_status(response, "fetch Cloud Run service")
            service = response.json()

        return CloudRunServiceRecord(
            service_name=service.get("name", "").split("/")[-1] or service_name,
            service_url=service.get("uri", ""),
            create_time=_parse_google_timestamp(service.get("createTime")),
        )

    async def _get_service(self, client: httpx.AsyncClient, service_name: str) -> dict[str, Any]:
        response = await client.get(
            f"{RUN_API_BASE}/{self._service_path(service_name)}",
            headers=await self._api_headers(),
        )
        self._raise_for_status(response, "fetch Cloud Run service")
        return response.json()

    async def _wait_for_operation(self, client: httpx.AsyncClient, operation_name: str) -> None:
        operation_url = f"{RUN_API_BASE}/{operation_name}"
        for _ in range(60):
            response = await client.get(operation_url, headers=await self._api_headers())
            self._raise_for_status(response, "poll Cloud Run operation")
            payload = response.json()
            if payload.get("done"):
                error = payload.get("error")
                if error:
                    raise GCPOperationError(error.get("message", "Cloud Run operation failed."))
                return
            await asyncio.sleep(2)
        raise GCPOperationError("Timed out waiting for Cloud Run operation to finish.")

    async def _api_headers(self) -> dict[str, str]:
        token = await asyncio.to_thread(self._access_token)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _access_token(self) -> str:
        credentials = self._get_credentials()
        credentials.refresh(Request())
        if not credentials.token:
            raise GCPOperationError("Could not obtain a Google Cloud access token.")
        return credentials.token

    def _get_credentials(self) -> Credentials:
        if self._credentials is None:
            credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
            self._credentials = credentials
        return self._credentials

    def _service_name_for_id(self, runner_id: str) -> str:
        return f"{RUNNER_SERVICE_PREFIX}{runner_id}".lower()

    def _service_path(self, service_name: str) -> str:
        return f"projects/{self.project_id}/locations/{self.region}/services/{service_name}"

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_google_error(response)
            raise GCPOperationError(f"Failed to {action}: {detail}") from exc


def _extract_google_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message", str(error))
        if isinstance(error, str):
            return error
    return str(payload)


def _parse_google_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)
