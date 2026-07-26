from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.legacy_migration import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_supported_types_contract():
    response = make_client().get("/api/migration/supported-types")
    assert response.status_code == 200
    body = response.json()
    assert "AP_INVOICE" in body["supported_doc_types"]
    assert body["source_systems"] == ["SQUARE9", "ZETADOCS"]


def test_preview_contract_and_filter():
    response = make_client().get(
        "/api/migration/preview", params={"source_filter": "SQUARE9", "limit": 3}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["preview_count"] <= 3
    assert body["filters"] == {"source_filter": "SQUARE9", "limit": 3}
    assert all(
        doc["legacy"]["metadata"]["legacy_system"] == "SQUARE9"
        for doc in body["documents"]
    )


def test_dry_run_contract():
    response = make_client().post(
        "/api/migration/run", json={"mode": "dry_run", "limit": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "dry_run"
    assert body["stats"]["total_processed"] == 2
    assert body["stats"]["total_errors"] == 0
    assert len(body["sample_documents"]) == 2


def test_invalid_mode_is_rejected():
    response = make_client().post(
        "/api/migration/run", json={"mode": "invalid", "limit": 1}
    )
    assert response.status_code == 400
    assert "Invalid mode" in response.json()["detail"]
