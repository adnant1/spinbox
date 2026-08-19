from __future__ import annotations

import httpx

from app.services.sandbox_client import _read_error_payload


def test_read_error_payload_unwraps_structured_detail() -> None:
    response = httpx.Response(
        400,
        headers={"content-type": "application/json"},
        json={
            "detail": {
                "error": "Sandbox validation failed",
                "detail": "name 'st' is not defined",
                "kind": "name_error",
                "line": None,
                "column": None,
            }
        },
    )

    payload = _read_error_payload(response)

    assert payload == {
        "error": "Sandbox validation failed",
        "detail": "name 'st' is not defined",
        "kind": "name_error",
        "line": None,
        "column": None,
    }
