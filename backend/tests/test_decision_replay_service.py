from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import pytest

from services.decision_replay_service import build_ap_decision_replay


class ReadOnlyCollection:
    def __init__(self, value: Any = None, resolver: Optional[Callable] = None):
        self.value = value
        self.resolver = resolver
        self.reads = []

    async def find_one(self, query, projection=None):
        self.reads.append((query, projection))
        if self.resolver:
            value = self.resolver(query, projection)
        else:
            value = self.value
        return dict(value) if isinstance(value, dict) else value

    async def insert_one(self, *_args, **_kwargs):
        raise AssertionError("decision replay attempted a Mongo insert")

    async def update_one(self, *_args, **_kwargs):
        raise AssertionError("decision replay attempted a Mongo update")

    async def delete_one(self, *_args, **_kwargs):
        raise AssertionError("decision replay attempted a Mongo delete")


class FakeDB:
    def __init__(
        self,
        *,
        sender=None,
        alias=None,
        bc_vendor=None,
        history=None,
        vendor_match=None,
    ):
        self.sender_vendor_map = ReadOnlyCollection(sender)
        self.vendor_aliases = ReadOnlyCollection(alias)
        self.hub_bc_vendors = ReadOnlyCollection(bc_vendor)
        self.hub_documents = ReadOnlyCollection(history)
        self.vendor_matches = ReadOnlyCollection(vendor_match)


def oi_document() -> Dict[str, Any]:
    return {
        "id": "oi-1",
        "file_name": "oi-invoice.pdf",
        "suggested_job_type": "AP_Invoice",
        "email_sender": "billing@gamerpackaging.com",
        "vendor_canonical": "VIT1",
        "vendor_match_method": "document_history",
        "bc_vendor_number": "VIT1",
        "extracted_fields": {
            "vendor": "O-I PACKAGING SOLUTIONS LLC",
            "invoice_number": "OI-100",
            "total_amount": "125.00",
        },
        "normalized_fields": {
            "vendor": "O-I PACKAGING SOLUTIONS LLC",
        },
        "validation_results": {
            "all_passed": True,
            "match_method": "document_history",
            "bc_record_info": {
                "displayName": "Gamer Packaging, Inc.",
                "number": "VIT1",
            },
        },
        "routing_suggestion_snapshot": {
            "folder_path": "",
            "reason": "staged for AP review",
            "source": "folder_routing_service",
            "capture_type": "pre_filing_routing",
        },
        "sharepoint_folder_path": "Temp Folder",
        "sharepoint_item_id": "sp-1",
    }


@pytest.mark.asyncio
async def test_oi_replay_rejects_contaminated_evidence_and_uses_bc_cache():
    contaminated_history = {
        "vendor_canonical": "Gamer Packaging, Inc.",
        "bc_vendor_number": "VIT1",
        "validation_results": {
            "bc_record_info": {
                "displayName": "Gamer Packaging, Inc.",
                "number": "VIT1",
            }
        },
    }
    db = FakeDB(
        sender={
            "sender_email": "billing@gamerpackaging.com",
            "vendor_canonical": "VIT1",
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
        },
        alias={
            "alias": "OI PACKAGING SOLUTIONS",
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
            "source": "auto_learned",
        },
        bc_vendor={
            "displayName": "O-I Packaging Solutions LLC",
            "number": "OIPACK",
        },
        history=contaminated_history,
        vendor_match={
            "matched_name": "Gamer Packaging, Inc.",
            "bc_vendor_number": "VIT1",
            "score": 1.0,
        },
    )

    replay = await build_ap_decision_replay(db, oi_document())

    resolution = replay["vendor_trace"]["resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["selected"]["source"] == "bc_cache_exact"
    assert resolution["selected"]["vendor_no"] == "OIPACK"
    assert replay["vendor_trace"]["rejected_count"] >= 4
    assert replay["current_rule_routing"]["uses_vendor"] == (
        "O-I Packaging Solutions LLC"
    )
    assert replay["writes"]["performed"] == []
    assert all(value is False for value in replay["guardrails"].values())


@pytest.mark.asyncio
async def test_oi_replay_fails_safe_when_only_conflicting_evidence_exists():
    db = FakeDB(
        sender={
            "vendor_canonical": "VIT1",
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
        },
        alias={
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
            "source": "auto_learned",
        },
        history={
            "vendor_canonical": "Gamer Packaging, Inc.",
            "bc_vendor_number": "VIT1",
        },
        vendor_match={
            "matched_name": "Gamer Packaging, Inc.",
            "bc_vendor_number": "VIT1",
        },
    )

    replay = await build_ap_decision_replay(db, oi_document())

    assert replay["vendor_trace"]["resolution"]["status"] == "unresolved"
    assert replay["current_rule_routing"]["uses_vendor"] == (
        "O-I PACKAGING SOLUTIONS LLC"
    )
    vendor_check = replay["validation_trace"]["local_safety_checks"][0]
    assert vendor_check["passed"] is False


@pytest.mark.asyncio
async def test_ball_history_is_accepted_as_compatible_identity():
    document = {
        "id": "ball-1",
        "file_name": "507240_6333386_2026-07-18.pdf",
        "suggested_job_type": "AP_Invoice",
        "vendor_canonical": "BALLCOR",
        "bc_vendor_number": "BALLCOR",
        "extracted_fields": {
            "vendor": "BALL METAL BEVERAGE CONTAINER CORP",
            "po_number": "W118410",
        },
        "validation_results": {
            "bc_record_info": {
                "displayName": "Ball Corp",
                "number": "BALLCOR",
            }
        },
        "sharepoint_folder_path": "Temp Folder/Warehouse Not International",
    }
    db = FakeDB(
        history={
            "vendor_canonical": "BALLCOR",
            "bc_vendor_number": "BALLCOR",
            "validation_results": {
                "bc_record_info": {
                    "displayName": "Ball Corp",
                    "number": "BALLCOR",
                }
            },
        }
    )

    replay = await build_ap_decision_replay(db, document)

    resolution = replay["vendor_trace"]["resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["selected"]["source"] == "document_history"
    assert resolution["selected"]["vendor_name"] == "Ball Corp"
    assert replay["current_rule_routing"]["uses_vendor"] == "Ball Corp"


@pytest.mark.asyncio
async def test_empty_snapshot_folder_is_preserved_as_temp_folder_match():
    document = oi_document()
    db = FakeDB(
        bc_vendor={
            "displayName": "O-I Packaging Solutions LLC",
            "number": "OIPACK",
        }
    )

    replay = await build_ap_decision_replay(db, document)

    historical = replay["historical_routing"]
    assert historical["original_suggestion"]["folder_path"] == "Temp Folder"
    assert historical["final_filing"]["folder_path"] == "Temp Folder"
    assert historical["original_matches_final"] is True


def test_router_exposes_decision_replay_path():
    from routers.decision_replay import router

    assert any(
        route.path == "/documents/{document_id}/decision-replay"
        for route in router.routes
    )
