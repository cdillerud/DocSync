from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import ap_validation as router_module
from routers.ap_validation import router


class FakeValidationResult:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)


@pytest.fixture
def documents_collection() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.find_one = AsyncMock()
    collection.update_one = AsyncMock()
    return collection


@pytest.fixture
def database(
    documents_collection: MagicMock,
) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = documents_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_validate_returns_404_for_missing_document(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    documents_collection.find_one.return_value = None

    with TestClient(app) as client:
        response = client.post(
            "/ap-validation/validate/missing-doc"
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found",
    }

    documents_collection.find_one.assert_awaited_once_with(
        {"id": "missing-doc"},
        {"_id": 0},
    )
    documents_collection.update_one.assert_not_awaited()


def test_validate_uses_injected_database_and_stores_result(
    app: FastAPI,
    database: MagicMock,
    documents_collection: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "id": "doc-1",
        "document_type": "AP_INVOICE",
        "matched_vendor_no": "V100",
        "matched_vendor_name": "Example Vendor",
        "vendor_match_method": "exact",
        "match_score": 0.98,
        "invoice_number_clean": "INV-123",
        "invoice_date": "2026-07-25",
        "amount_float": 125.50,
        "vendor_raw": "Example Vendor",
        "po_number_clean": "PO-99",
    }
    documents_collection.find_one.return_value = document

    validation_payload = {
        "validation_state": "pass",
        "all_passed": True,
        "blocking_issues": [],
        "warnings": [],
        "checks": [
            {"name": "vendor", "passed": True},
            {"name": "invoice", "passed": True},
        ],
        "vendor_resolved": True,
        "invoice_number_present": True,
        "invoice_date_present": True,
        "total_amount_present": True,
        "is_duplicate": False,
    }

    validation_service = MagicMock(name="validation_service")
    validation_service.validate_ap_invoice = AsyncMock(
        return_value=FakeValidationResult(validation_payload)
    )

    validation_service_class = MagicMock(
        return_value=validation_service
    )

    bc_service = MagicMock(name="bc_service")
    event_service = MagicMock(name="event_service")
    event_service.emit = AsyncMock()

    monkeypatch.setattr(
        router_module,
        "APValidationService",
        validation_service_class,
    )
    monkeypatch.setattr(
        router_module,
        "_get_bc_service",
        lambda: bc_service,
    )
    monkeypatch.setattr(
        router_module,
        "_get_event_service",
        lambda: event_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ap-validation/validate/doc-1"
        )

    assert response.status_code == 200

    body = response.json()
    assert body["validation_state"] == "pass"
    assert body["validation_version"] == "2.0.0"
    assert body["validation_source"] == "manual_trigger"

    validation_service_class.assert_called_once_with(
        database,
        bc_service=bc_service,
        event_service=event_service,
    )

    validation_service.validate_ap_invoice.assert_awaited_once()

    call = validation_service.validate_ap_invoice.await_args
    assert call.kwargs["document"] == document
    assert call.kwargs["extracted_fields"] == {
        "invoice_number": "INV-123",
        "invoice_date": "2026-07-25",
        "amount": 125.50,
        "vendor": "Example Vendor",
        "po_number": "PO-99",
    }
    assert call.kwargs["vendor_match_result"] == {
        "matched": True,
        "bc_vendor_number": "V100",
        "best_match": {
            "vendor_number": "V100",
            "name": "Example Vendor",
        },
        "source": "exact",
        "score": 0.98,
    }

    documents_collection.update_one.assert_awaited_once()

    update_call = documents_collection.update_one.await_args
    assert update_call.args[0] == {"id": "doc-1"}

    stored = update_call.args[1]["$set"]
    assert stored["validation_state"] == "pass"
    assert stored["validation_passed"] is True
    assert stored["derived_workflow_state"] == "ready"
    assert stored["derived_automation_state"] == "assisted"
    assert stored["validation_summary"] == "Validated: 2/2 checks"
    assert stored["validation_version"] == "2.0.0"
    assert "validation_last_run" in stored
    assert "updated_utc" in stored

    event_service.emit.assert_awaited_once_with(
        event_type="validation.completed",
        document_id="doc-1",
        status="completed",
        source_service="ap_validation_manual",
        payload={
            "document_type": "AP_INVOICE",
            "validation_state": "pass",
            "all_passed": True,
            "blocking_issues_count": 0,
            "warnings_count": 0,
            "vendor_resolved": True,
            "invoice_number_present": True,
            "invoice_date_present": True,
            "total_amount_present": True,
            "is_duplicate": False,
        },
    )


@pytest.mark.parametrize(
    (
        "validation_state",
        "workflow_state",
        "automation_state",
        "validation_passed",
        "summary_prefix",
    ),
    [
        (
            "warning",
            "reviewing",
            "assisted",
            True,
            "Validated",
        ),
        (
            "fail",
            "needs_review",
            "manual",
            False,
            "Failed",
        ),
    ],
)
def test_validate_derives_expected_states(
    app: FastAPI,
    documents_collection: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    validation_state: str,
    workflow_state: str,
    automation_state: str,
    validation_passed: bool,
    summary_prefix: str,
) -> None:
    documents_collection.find_one.return_value = {
        "id": "doc-state",
        "vendor_canonical": "Unmatched Vendor",
        "extracted_fields": {
            "invoice_number": "INV-1",
        },
    }

    validation_service = MagicMock()
    validation_service.validate_ap_invoice = AsyncMock(
        return_value=FakeValidationResult(
            {
                "validation_state": validation_state,
                "all_passed": False,
                "blocking_issues": ["problem"],
                "warnings": [
                    {"details": "warning detail"},
                ],
                "checks": [
                    {"name": "one", "passed": True},
                    {"name": "two", "passed": False},
                ],
            }
        )
    )

    monkeypatch.setattr(
        router_module,
        "APValidationService",
        MagicMock(return_value=validation_service),
    )
    monkeypatch.setattr(
        router_module,
        "_get_bc_service",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        router_module,
        "_get_event_service",
        lambda: None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ap-validation/validate/doc-state"
        )

    assert response.status_code == 200

    update_call = documents_collection.update_one.await_args
    stored = update_call.args[1]["$set"]

    assert stored["validation_state"] == validation_state
    assert stored["validation_passed"] is validation_passed
    assert stored["derived_workflow_state"] == workflow_state
    assert stored["derived_automation_state"] == automation_state
    assert stored["validation_summary"] == (
        f"{summary_prefix}: 1/2 checks"
    )
    assert stored["validation_errors"] == ["problem"]
    assert stored["validation_warnings"] == [
        "warning detail"
    ]


def test_validate_uses_unified_vendor_match(
    app: FastAPI,
    documents_collection: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents_collection.find_one.return_value = {
        "id": "doc-uvm",
        "unified_vendor_match": {
            "bc_vendor_number": "V200",
            "best_match": {
                "name": "Unified Vendor",
            },
            "source": "unified",
            "score": 0.91,
        },
    }

    validation_service = MagicMock()
    validation_service.validate_ap_invoice = AsyncMock(
        return_value=FakeValidationResult(
            {
                "validation_state": "pass",
                "blocking_issues": [],
                "warnings": [],
                "checks": [],
            }
        )
    )

    monkeypatch.setattr(
        router_module,
        "APValidationService",
        MagicMock(return_value=validation_service),
    )
    monkeypatch.setattr(
        router_module,
        "_get_bc_service",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        router_module,
        "_get_event_service",
        lambda: None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ap-validation/validate/doc-uvm"
        )

    assert response.status_code == 200

    validation_call = (
        validation_service.validate_ap_invoice.await_args
    )
    assert validation_call.kwargs[
        "vendor_match_result"
    ] == {
        "matched": True,
        "bc_vendor_number": "V200",
        "best_match": {
            "vendor_number": "V200",
            "name": "Unified Vendor",
        },
        "source": "unified",
        "score": 0.91,
    }


def test_validate_uses_business_central_vendor_fallback(
    app: FastAPI,
    documents_collection: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents_collection.find_one.return_value = {
        "id": "doc-bc",
        "validation_results": {
            "bc_record_info": {
                "number": "V300",
                "displayName": "BC Vendor",
            }
        },
    }

    validation_service = MagicMock()
    validation_service.validate_ap_invoice = AsyncMock(
        return_value=FakeValidationResult(
            {
                "validation_state": "pass",
                "blocking_issues": [],
                "warnings": [],
                "checks": [],
            }
        )
    )

    monkeypatch.setattr(
        router_module,
        "APValidationService",
        MagicMock(return_value=validation_service),
    )
    monkeypatch.setattr(
        router_module,
        "_get_bc_service",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        router_module,
        "_get_event_service",
        lambda: None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ap-validation/validate/doc-bc"
        )

    assert response.status_code == 200

    validation_call = (
        validation_service.validate_ap_invoice.await_args
    )
    vendor_match = validation_call.kwargs[
        "vendor_match_result"
    ]

    assert vendor_match["matched"] is True
    assert vendor_match["bc_vendor_number"] == "V300"
    assert vendor_match["best_match"] == {
        "vendor_number": "V300",
        "name": "BC Vendor",
    }


def test_status_uses_injected_database(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    stored_status = {
        "ap_validation_result": {
            "validation_state": "pass",
        },
        "validation_state": "pass",
        "validation_passed": True,
        "validation_summary": "Validated: 4/4 checks",
        "validation_version": "2.0.0",
        "derived_workflow_state": "ready",
        "derived_automation_state": "assisted",
    }
    documents_collection.find_one.return_value = stored_status

    with TestClient(app) as client:
        response = client.get(
            "/ap-validation/status/doc-1"
        )

    assert response.status_code == 200
    assert response.json() == stored_status

    documents_collection.find_one.assert_awaited_once_with(
        {"id": "doc-1"},
        {
            "_id": 0,
            "ap_validation_result": 1,
            "validation_state": 1,
            "validation_passed": 1,
            "validation_errors": 1,
            "validation_warnings": 1,
            "validation_summary": 1,
            "validation_version": 1,
            "validation_last_run": 1,
            "derived_workflow_state": 1,
            "derived_automation_state": 1,
        },
    )


def test_status_returns_404_for_missing_document(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    documents_collection.find_one.return_value = None

    with TestClient(app) as client:
        response = client.get(
            "/ap-validation/status/missing"
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found",
    }


def test_database_dependencies_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/ap-validation/validate/{doc_id}"]["post"],
        paths["/ap-validation/status/{doc_id}"]["get"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_router_source_has_no_legacy_database_dependency() -> None:
    source_path = router_module.__file__

    assert source_path is not None

    with open(source_path, encoding="utf-8") as router_file:
        source = router_file.read()

    assert "from deps import get_db" not in source
    assert "get_db()" not in source
    assert "db.hub_documents" not in source
    assert source.count(
        "Depends(get_platform_database)"
    ) == 2
    assert source.count(
        "database.hub_documents"
    ) == 3
