from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_reports_ok_and_capabilities(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["capabilities"] == {
        "hunar": False,
        "nvidia": False,
        "pdl": False,
        "gemini": False,
    }
