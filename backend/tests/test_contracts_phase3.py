"""Phase 3 — Analytics endpoints, env-driven thresholds, parameterized pricing.

Run:
    cd /app/backend && python -m pytest tests/test_contracts_phase3.py -q
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import deps
from models.contracts import CONTRACTS_COLLECTIONS, CONTRACTS_INDEXES
from services.auth_deps import get_current_user
from services.contracts.bc_agreement_matcher import InMemoryBCRepository
from services.contracts.contract_intelligence_service import (
    ContractIntelligenceService,
)
import services.integrations.docusign_client as ds_module
from services.integrations.docusign_client import (
    DocuSignClient,
    DocuSignSettings,
    reset_docusign_client_for_tests,
)


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def configured_singleton(monkeypatch):
    reset_docusign_client_for_tests()
    settings = DocuSignSettings(
        integration_key="ik", user_id="uid", account_id="acc",
        oauth_host="account-d.docusign.com",
        hmac_secrets=("phase3-secret",),
    )
    client = DocuSignClient(settings)
    monkeypatch.setattr(ds_module, "_singleton", client)
    yield client
    reset_docusign_client_for_tests()


@pytest.fixture()
def app_and_db():
    client = AsyncMongoMockClient()
    database = client["contracts_test_phase3"]

    # Use a fresh event loop — asyncio.get_event_loop() raises on
    # Python 3.10+ once the default loop has been closed by an earlier
    # test in the run.
    async def _materialize():
        for coll_name, specs in CONTRACTS_INDEXES.items():
            coll = database[CONTRACTS_COLLECTIONS[coll_name]]
            for spec in specs:
                kwargs = {k: v for k, v in spec.items() if k != "keys"}
                await coll.create_index(spec["keys"], **kwargs)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_materialize())
    finally:
        loop.close()
    deps.set_db(database)

    from routers.contracts import router as contracts_router
    app = FastAPI()
    app.include_router(contracts_router, prefix="/api")

    async def fake_user():
        return {"id": "u-1", "email": "alice@gpi.com", "role": "admin"}
    app.dependency_overrides[get_current_user] = fake_user
    return app, database


# ---------------------------------------------------------------------------
# Env-driven thresholds
# ---------------------------------------------------------------------------

class TestThresholdsEnv:
    def test_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD", raising=False)
        monkeypatch.delenv("CONTRACT_MATCH_PROPOSE_THRESHOLD", raising=False)
        # Re-import the module to re-evaluate module-level constants
        import services.contracts.bc_agreement_matcher as m
        importlib.reload(m)
        assert m.AUTO_CONFIRM_THRESHOLD == 0.95
        assert m.MIN_PROPOSE_THRESHOLD == 0.80

    def test_env_override_applied(self, monkeypatch):
        monkeypatch.setenv("CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD", "0.88")
        monkeypatch.setenv("CONTRACT_MATCH_PROPOSE_THRESHOLD", "0.55")
        import services.contracts.bc_agreement_matcher as m
        importlib.reload(m)
        assert m.AUTO_CONFIRM_THRESHOLD == 0.88
        assert m.MIN_PROPOSE_THRESHOLD == 0.55

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD", "not-a-number")
        monkeypatch.setenv("CONTRACT_MATCH_PROPOSE_THRESHOLD", "1.5")
        import services.contracts.bc_agreement_matcher as m
        importlib.reload(m)
        assert m.AUTO_CONFIRM_THRESHOLD == 0.95
        assert m.MIN_PROPOSE_THRESHOLD == 0.80


# ---------------------------------------------------------------------------
# Parameterized pricing convention
# ---------------------------------------------------------------------------

class TestPricingRegexEnv:
    def test_default_convention_still_works(self, monkeypatch):
        monkeypatch.delenv("CONTRACT_PRICING_TAB_REGEX", raising=False)
        import services.contracts.agreement_normalizer as n
        importlib.reload(n)
        payload = {
            "envelopeId": "e-1",
            "status": "completed",
            "formData": [
                {"name": "line_1_item", "value": "WIDGET"},
                {"name": "line_1_qty", "value": "10"},
                {"name": "line_1_price", "value": "5"},
            ],
        }
        out = n.normalize_envelope(payload)
        assert len(out.pricing) == 1
        assert out.pricing[0].item_label == "WIDGET"

    def test_custom_regex_picks_up_alt_naming(self, monkeypatch):
        # Custom convention: `lineitem_N_attr` (e.g. lineitem_1_sku)
        monkeypatch.setenv(
            "CONTRACT_PRICING_TAB_REGEX",
            r"^lineitem[_\-]?(\d+)[_\-]?(.+)$",
        )
        import services.contracts.agreement_normalizer as n
        importlib.reload(n)
        payload = {
            "envelopeId": "e-2",
            "status": "completed",
            "formData": [
                {"name": "lineitem_1_item", "value": "GIZMO"},
                {"name": "lineitem_1_qty", "value": "3"},
                {"name": "lineitem_1_price", "value": "2.0"},
                # Old `line_N_*` rows now go to TERMS, not pricing.
                {"name": "line_1_item", "value": "should_be_term_now"},
            ],
        }
        out = n.normalize_envelope(payload)
        assert len(out.pricing) == 1
        assert out.pricing[0].item_label == "GIZMO"
        # The legacy line_1_item should now be a term (since it doesn't match
        # the new pricing regex). It should NOT be filtered as pricing-bound.
        assert any(t.term_key == "line_1_item" for t in out.terms)

    def test_invalid_regex_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CONTRACT_PRICING_TAB_REGEX", "(unclosed[")
        import services.contracts.agreement_normalizer as n
        importlib.reload(n)
        payload = {
            "envelopeId": "e-3",
            "status": "completed",
            "formData": [
                {"name": "line_1_item", "value": "FALLBACK"},
                {"name": "line_1_qty", "value": "1"},
            ],
        }
        out = n.normalize_envelope(payload)
        # default regex still works
        assert len(out.pricing) == 1
        assert out.pricing[0].item_label == "FALLBACK"


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def seeded(app_and_db):
    app, db = app_and_db
    # Two agreements: one with linked customer and exception, one expiring soon.
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(days=10)).isoformat()
    far = (now + timedelta(days=200)).isoformat()
    past = (now - timedelta(days=5)).isoformat()

    await db[CONTRACTS_COLLECTIONS["agreements"]].insert_many([
        {
            "id": "agr-1", "provider": "docusign",
            "provider_envelope_id": "env-1", "status": "completed",
            "expires_at": soon, "has_unmatched_exceptions": False,
            "updated_at": now.isoformat(),
        },
        {
            "id": "agr-2", "provider": "docusign",
            "provider_envelope_id": "env-2", "status": "sent",
            "expires_at": far, "has_unmatched_exceptions": True,
            "updated_at": now.isoformat(),
        },
        {
            "id": "agr-3", "provider": "docusign",
            "provider_envelope_id": "env-3", "status": "voided",
            "expires_at": past, "has_unmatched_exceptions": False,
            "updated_at": now.isoformat(),
        },
    ])
    await db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].insert_many([
        {"id": "ex-1", "agreement_id": "agr-2", "code": "party_unmatched",
         "severity": "medium", "details": {}, "status": "open"},
        {"id": "ex-2", "agreement_id": "agr-2", "code": "item_unmatched",
         "severity": "low", "details": {}, "status": "open"},
        {"id": "ex-3", "agreement_id": "agr-1", "code": "party_unmatched",
         "severity": "low", "details": {}, "status": "resolved"},
    ])
    await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_many([
        {"id": "lk-1", "agreement_id": "agr-1", "link_type": "customer",
         "bc_entity": "customers", "bc_no": "C-1", "match_method": "exact_name",
         "confidence": 0.99, "status": "auto_confirmed", "linked_by": "system"},
        {"id": "lk-2", "agreement_id": "agr-1", "link_type": "item",
         "bc_entity": "items", "bc_no": "I-1", "match_method": "fuzzy",
         "confidence": 0.85, "status": "proposed", "linked_by": "system",
         "pricing_id": "pr-1"},
        {"id": "lk-3", "agreement_id": "agr-2", "link_type": "vendor",
         "bc_entity": "vendors", "bc_no": "V-1", "match_method": "fuzzy",
         "confidence": 0.82, "status": "proposed", "linked_by": "system"},
    ])
    await db[CONTRACTS_COLLECTIONS["agreement_pricing"]].insert_many([
        {"id": "pr-1", "agreement_id": "agr-1", "line_no": 1,
         "item_label": "WIDGET", "matched_bc_item_no": "I-1"},
        {"id": "pr-2", "agreement_id": "agr-2", "line_no": 1,
         "item_label": "UNKNOWN", "matched_bc_item_no": None},
    ])
    await db[CONTRACTS_COLLECTIONS["agreement_events"]].insert_many([
        {"id": "ev-1", "provider": "docusign", "provider_event_id": "e-1",
         "event_type": "envelope-sent", "raw_payload": {}, "processed": True,
         "received_at": now},
        {"id": "ev-2", "provider": "docusign", "provider_event_id": "e-2",
         "event_type": "envelope-completed", "raw_payload": {}, "processed": False,
         "received_at": now},
    ])
    await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].insert_many([
        {"id": "au-1", "agreement_id": "agr-1", "action": "proposed_link",
         "actor": "system", "link_id": "lk-1", "after": {"link_type": "customer"},
         "at": now.isoformat()},
        {"id": "au-2", "agreement_id": "agr-1", "action": "rejected_link",
         "actor": "alice@gpi.com", "link_id": "lk-1",
         "before": {"status": "auto_confirmed"}, "after": {"status": "rejected"},
         "at": now.isoformat()},
        {"id": "au-3", "agreement_id": "agr-2", "action": "proposed_link",
         "actor": "system", "link_id": "lk-3", "after": {"link_type": "vendor"},
         "at": now.isoformat()},
    ])
    return app, db


class TestSummary:
    def test_summary_counts(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["agreements"]["total"] == 3
        assert body["agreements"]["by_status"]["completed"] == 1
        assert body["agreements"]["by_status"]["sent"] == 1
        assert body["agreements"]["by_status"]["voided"] == 1
        assert body["agreements"]["with_unmatched_exceptions"] == 1
        assert body["exceptions"]["open"] == 2
        assert body["exceptions"]["resolved"] == 1
        assert body["exceptions"]["by_code"]["party_unmatched"] == 1
        assert body["exceptions"]["by_code"]["item_unmatched"] == 1
        assert body["links"]["total"] == 3
        assert body["links"]["by_type"]["customer"] == 1
        assert body["links"]["by_type"]["vendor"] == 1
        assert body["links"]["by_type"]["item"] == 1
        assert body["events"]["total"] == 2
        assert body["events"]["unprocessed"] == 1


class TestExpiring:
    def test_expiring_within_default_window(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/expiring", params={"within_days": 60})
        assert r.status_code == 200
        body = r.json()
        # Only agr-1 (10 days) qualifies; agr-3 already past + voided; agr-2 too far
        ids = [item["id"] for item in body["items"]]
        assert "agr-1" in ids
        assert "agr-2" not in ids
        assert "agr-3" not in ids
        assert body["total"] == 1

    def test_expiring_excludes_voided(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/expiring", params={"within_days": 365})
        body = r.json()
        # agr-3 is voided AND already past — must be excluded
        assert all(item["id"] != "agr-3" for item in body["items"])


class TestCoverage:
    def test_coverage_ratios(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/coverage")
        assert r.status_code == 200
        body = r.json()
        assert body["agreements_total"] == 3
        # Customer: only agr-1 has a customer link → 1/3
        assert body["customer_coverage"]["covered"] == 1
        assert body["customer_coverage"]["uncovered"] == 2
        # Vendor: only agr-2 → 1/3
        assert body["vendor_coverage"]["covered"] == 1
        # Item: only agr-1 has an item link
        assert body["item_coverage"]["agreements_with_item_links"] == 1
        # Pricing: 1 of 2 matched
        assert body["pricing_lines"]["total"] == 2
        assert body["pricing_lines"]["matched"] == 1
        assert body["pricing_lines"]["match_ratio"] == 0.5


class TestThresholdTelemetry:
    def test_telemetry_basic_counts(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/threshold-telemetry", params={"days": 7})
        assert r.status_code == 200
        body = r.json()
        # 2 system-emitted links (lk-1 + lk-3); lk-1 was rejected by a human
        assert body["system_emitted"] == 2
        assert body["human_overrides"] == 1
        assert body["override_rate"] == 0.5
        # Bands: lk-1 (0.99) → auto_confirm; lk-3 (0.82) → propose
        assert body["by_threshold_band"]["auto_confirm"] == 1
        assert body["by_threshold_band"]["propose"] == 1


class TestAuditTrail:
    def test_audit_for_agreement(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/audit/agr-1")
        assert r.status_code == 200
        items = r.json()["items"]
        actions = [a["action"] for a in items]
        assert "proposed_link" in actions
        assert "rejected_link" in actions

    def test_audit_for_unknown_agreement_empty(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/audit/nope")
        assert r.status_code == 200
        assert r.json()["total"] == 0


class TestHealthVendorTelemetry:
    def test_health_surfaces_vendor_link_counts(self, seeded, configured_singleton):
        app, _ = seeded
        c = TestClient(app)
        r = c.get("/api/contracts/health")
        assert r.status_code == 200
        body = r.json()
        assert body["module"] == "contract_intelligence"
        assert "vendor_link_telemetry" in body
        # 1 proposed vendor link (au-3) + 0 confirmed vendor links
        assert body["vendor_link_telemetry"]["proposed_vendor_links_total"] == 1
        assert body["vendor_link_telemetry"]["confirmed_vendor_links_total"] == 0
