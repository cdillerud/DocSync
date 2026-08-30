import asyncio
from types import SimpleNamespace

from services.ap_routing_shadow_service import (
    build_shadow_telemetry,
    evaluate_ap_routing_shadow,
    is_ap_shadow_candidate,
    normalize_authoritative_route,
    predicted_temp_folder,
    register_ap_routing_shadow_subscriber,
)


class _UpdateResult:
    modified_count = 1


class _Collection:
    def __init__(self):
        self.updates = []

    async def update_one(self, query, update):
        self.updates.append((query, update))
        return _UpdateResult()


class _DB:
    def __init__(self):
        self.hub_documents = _Collection()


class _EventService:
    def __init__(self):
        self.registrations = []

    def register_subscriber(self, pattern, callback):
        self.registrations.append((pattern, callback))


def _analysis(route, *, auto=True, classification_confidence=0.97, routing_confidence=0.98):
    return {
        "schema_version": "2.0",
        "classification_confidence": classification_confidence,
        "contract_version": "test-contract-v1",
        "proposed_temp_route": route,
        "auto_route_ready": auto,
        "manual_validation_required": not auto,
        "bc_context": {"status": "resolved", "po_number": "110784A"},
        "routing": {
            "decision": "auto_route" if auto else "needs_review",
            "route_path": route,
            "confidence": routing_confidence,
            "reason": "test route",
            "blockers": [] if auto else ["needs more evidence"],
            "warnings": [],
            "contract_version": "test-contract-v1",
            "prediction": {"model": "test-model"},
        },
    }


def test_candidate_gate_includes_payables_and_ap_mailbox_only():
    assert is_ap_shadow_candidate({"doc_type": "AP_INVOICE"})
    assert is_ap_shadow_candidate({"document_type": "Credit_Memo"})
    assert is_ap_shadow_candidate({"mailbox_category": "AP", "doc_type": "Other"})
    assert not is_ap_shadow_candidate({"doc_type": "SALES_INVOICE", "mailbox_category": "SALES"})


def test_authoritative_route_normalizes_full_production_temp_path():
    assert normalize_authoritative_route(
        "General/Accounting/Accounts Payable/Temp Folder/Dropship Not International/Freight"
    ) == "Dropship Not International/Freight"


def test_authoritative_temp_root_normalizes_to_empty_relative_route():
    assert normalize_authoritative_route(
        "General/Accounting/Accounts Payable/Temp Folder"
    ) == ""
    assert normalize_authoritative_route("Temp Folder") == ""


def test_relative_test_route_is_preserved():
    assert normalize_authoritative_route("Warehouse Not International") == "Warehouse Not International"


def test_empty_prediction_means_temp_root_not_fabricated_needs_review_folder():
    assert predicted_temp_folder("") == "Temp Folder"
    assert "_NeedsReview" not in predicted_temp_folder("")


def test_correct_auto_route_is_coverage_candidate():
    telemetry = build_shadow_telemetry(
        document_id="doc-1",
        file_name="invoice.pdf",
        authoritative_folder=(
            "General/Accounting/Accounts Payable/Temp Folder/"
            "Dropship Not International/Freight"
        ),
        analysis=_analysis("Dropship Not International/Freight", auto=True),
    )
    assert telemetry["agreement"] is True
    assert telemetry["auto_route_ready"] is True
    assert telemetry["coverage_candidate"] is True
    assert telemetry["wrong_auto_route"] is False
    assert telemetry["disposition"] == "auto_route_agreement"


def test_wrong_auto_route_is_explicit_regression_failure():
    telemetry = build_shadow_telemetry(
        document_id="doc-2",
        file_name="tumalo.pdf",
        authoritative_folder=(
            "General/Accounting/Accounts Payable/Temp Folder/"
            "Warehouse Not International"
        ),
        analysis=_analysis("Dropship Not International/Freight", auto=True),
    )
    assert telemetry["agreement"] is False
    assert telemetry["coverage_candidate"] is False
    assert telemetry["wrong_auto_route"] is True
    assert telemetry["disposition"] == "auto_route_disagreement"


def test_correct_prediction_that_still_requires_review_does_not_count_as_coverage():
    telemetry = build_shadow_telemetry(
        document_id="doc-3",
        file_name="invoice.pdf",
        authoritative_folder="Warehouse Not International",
        analysis=_analysis("Warehouse Not International", auto=False),
    )
    assert telemetry["agreement"] is True
    assert telemetry["auto_route_ready"] is False
    assert telemetry["manual_validation_required"] is True
    assert telemetry["coverage_candidate"] is False
    assert telemetry["wrong_auto_route"] is False
    assert telemetry["disposition"] == "review_agreement"


def test_model_exception_is_contained_and_returns_shadow_error():
    async def failing_analyzer(*args, **kwargs):
        raise RuntimeError("synthetic model failure")

    result = asyncio.run(
        evaluate_ap_routing_shadow(
            None,
            document_id="doc-4",
            file_path="/tmp/not-used.pdf",
            file_name="invoice.pdf",
            authoritative_folder="Warehouse Not International",
            persist=False,
            analyzer=failing_analyzer,
        )
    )
    assert result["status"] == "error"
    assert result["auto_route_ready"] is False
    assert result["wrong_auto_route"] is False
    assert result["disposition"] == "shadow_error"
    assert "RuntimeError" in result["error"]


def test_model_timeout_is_contained_and_returns_shadow_timeout():
    async def slow_analyzer(*args, **kwargs):
        await asyncio.sleep(0.05)
        return _analysis("Warehouse Not International")

    result = asyncio.run(
        evaluate_ap_routing_shadow(
            None,
            document_id="doc-5",
            file_path="/tmp/not-used.pdf",
            file_name="invoice.pdf",
            authoritative_folder="Warehouse Not International",
            persist=False,
            timeout_seconds=0.001,
            analyzer=slow_analyzer,
        )
    )
    assert result["status"] == "timeout"
    assert result["auto_route_ready"] is False
    assert result["wrong_auto_route"] is False
    assert result["disposition"] == "shadow_timeout"


def test_persistence_writes_shadow_telemetry_only():
    async def analyzer(*args, **kwargs):
        return _analysis("Warehouse Not International")

    db = _DB()
    result = asyncio.run(
        evaluate_ap_routing_shadow(
            db,
            document_id="doc-6",
            file_path="/tmp/not-used.pdf",
            file_name="invoice.pdf",
            authoritative_folder="Warehouse Not International",
            persist=True,
            analyzer=analyzer,
        )
    )
    assert result["status"] == "completed"
    assert len(db.hub_documents.updates) == 1
    query, update = db.hub_documents.updates[0]
    assert query == {"id": "doc-6"}
    assert set(update) == {"$set"}
    assert set(update["$set"]) == {
        "ap_routing_shadow",
        "ap_routing_shadow_last_evaluated_utc",
    }
    forbidden = {
        "sharepoint_folder_path",
        "routing_status",
        "routing_reason",
        "status",
        "workflow_status",
        "bc_record_id",
        "automation_decision",
    }
    assert not (forbidden & set(update["$set"]))


def test_registration_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AP_AI_ROUTING_SHADOW_ENABLED", raising=False)
    event_service = _EventService()
    assert register_ap_routing_shadow_subscriber(event_service, object()) is False
    assert event_service.registrations == []


def test_registration_when_enabled_only_subscribes_to_post_upload_event(monkeypatch):
    monkeypatch.setenv("AP_AI_ROUTING_SHADOW_ENABLED", "true")
    event_service = _EventService()
    assert register_ap_routing_shadow_subscriber(event_service, object()) is True
    assert len(event_service.registrations) == 1
    pattern, callback = event_service.registrations[0]
    assert pattern == "sharepoint.upload.succeeded"
    assert callable(callback)
