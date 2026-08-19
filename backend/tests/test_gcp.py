from datetime import UTC

from app.services.gcp import GCPClient, _parse_google_timestamp


def test_cloud_run_resource_paths_are_not_percent_encoded() -> None:
    client = GCPClient(
        project_id="example-project",
        region="us-central1",
        image_uri="us-central1-docker.pkg.dev/example-project/spinbox-repo/sandbox-runner:latest",
    )

    service_path = client._service_path("spinbox-runner-abcd1234")

    assert service_path == "projects/example-project/locations/us-central1/services/spinbox-runner-abcd1234"


def test_parse_google_timestamp_returns_utc_datetime() -> None:
    parsed = _parse_google_timestamp("2026-04-07T14:30:00.000Z")

    assert parsed is not None
    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2026-04-07T14:30:00+00:00"
