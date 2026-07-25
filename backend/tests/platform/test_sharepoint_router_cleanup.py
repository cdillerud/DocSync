from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import sharepoint
from routers.sharepoint import router


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    return application


def test_folder_structure_endpoint_returns_configured_structure(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sharepoint,
        "FOLDER_STRUCTURE",
        {"Accounting": {"Invoices": {}}},
    )
    monkeypatch.setattr(
        sharepoint,
        "VENDOR_FOLDER_MAPPING",
        {"Vendor A": "Accounting/Invoices"},
    )
    monkeypatch.setattr(
        sharepoint,
        "get_all_folder_paths",
        lambda: [
            "Accounting",
            "Accounting/Invoices",
        ],
    )
    monkeypatch.setattr(
        sharepoint,
        "get_folder_structure_summary",
        lambda: {"folders": 2},
    )

    with TestClient(app) as client:
        response = client.get("/sharepoint/folder-structure")

    assert response.status_code == 200
    assert response.json() == {
        "structure": {"Accounting": {"Invoices": {}}},
        "vendor_mapping": {
            "Vendor A": "Accounting/Invoices"
        },
        "all_folders": [
            "Accounting",
            "Accounting/Invoices",
        ],
        "total_folders": 2,
        "summary": {"folders": 2},
    }


def test_initialize_folders_reports_created_and_failed(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sharepoint,
        "get_all_folder_paths",
        lambda: ["Folder A", "Folder B", "Folder C"],
    )

    ensure_folder = AsyncMock(
        side_effect=[
            True,
            False,
            RuntimeError("SharePoint unavailable"),
        ]
    )

    monkeypatch.setattr(
        "services.sharepoint_service."
        "ensure_sharepoint_folder_exists",
        ensure_folder,
    )

    with TestClient(app) as client:
        response = client.post(
            "/sharepoint/initialize-folders"
        )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Initialized 1 folders",
        "results": {
            "total": 3,
            "created": ["Folder A"],
            "existing": [],
            "failed": [
                {
                    "folder": "Folder B",
                    "error": "Unknown error",
                },
                {
                    "folder": "Folder C",
                    "error": "SharePoint unavailable",
                },
            ],
        },
    }

    assert ensure_folder.await_count == 3


def test_test_routing_uses_submitted_form_values(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    determine_folder_path = AsyncMock()

    def fake_determine_folder_path(
        *,
        doc_type: str,
        vendor: str,
        order_number: str,
    ) -> str:
        assert doc_type == "AP_Invoice"
        assert vendor == "Vendor A"
        assert order_number == "PO-123"
        return "Accounting/AP/Vendor A"

    monkeypatch.setattr(
        sharepoint,
        "determine_folder_path",
        fake_determine_folder_path,
    )

    with TestClient(app) as client:
        response = client.post(
            "/sharepoint/test-routing",
            data={
                "doc_type": "AP_Invoice",
                "vendor": "Vendor A",
                "order_number": "PO-123",
                "freight_direction": "Inbound",
                "is_international": "true",
                "description": "Invoice test",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "input": {
            "doc_type": "AP_Invoice",
            "vendor": "Vendor A",
            "order_number": "PO-123",
            "freight_direction": "Inbound",
            "is_international": True,
            "description": "Invoice test",
        },
        "routed_folder": "Accounting/AP/Vendor A",
    }


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/sharepoint/folder-structure", "get"),
        ("/sharepoint/initialize-folders", "post"),
        ("/sharepoint/test-routing", "post"),
    ],
)
def test_sharepoint_routes_do_not_expose_database_parameter(
    app: FastAPI,
    path: str,
    method: str,
) -> None:
    operation = app.openapi()["paths"][path][method]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] not in {"db", "database"}
        for parameter in parameters
    )


def test_router_source_has_no_legacy_database_dependency() -> None:
    source = sharepoint.__file__

    assert source is not None

    with open(source, encoding="utf-8") as router_file:
        router_source = router_file.read()

    assert "get_db" not in router_source
    assert "from deps import" not in router_source
