"""Phase 3.1 — Tighter telemetry banding + scoped BC search.

Run:
    cd /app/backend && python -m pytest tests/test_contracts_phase3_1.py -q
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import deps
from models.contracts import CONTRACTS_COLLECTIONS, CONTRACTS_INDEXES
from services.auth_deps import get_current_user
import services.integrations.docusign_client as ds_module
from services.integrations.docusign_client import (
    DocuSignClient,
    DocuSignSettings,
    reset_docusign_client_for_tests,
)


@pytest.fixture()
def configured_singleton(monkeypatch):
    reset_docusign_client_for_tests()
    settings = DocuSignSettings(
        integration_key="ik", user_id="uid", account_id="acc",
        oauth_host="account-d.docusign.com",
        hmac_secrets=("phase31-secret",),
    )
    client = DocuSignClient(settings)
    monkeypatch.setattr(ds_module, "_singleton", client)
    yield client
    reset_docusign_client_for_tests()


@pytest_asyncio.fixture()
async def app_db():
    client = AsyncMongoMockClient()
    database = client["contracts_test_phase31"]
    for coll_name, specs in CONTRACTS_INDEXES.items():
        coll = database[CONTRACTS_COLLECTIONS[coll_name]]
        for spec in specs:
            kwargs = {k: v for k, v in spec.items() if k != "keys"}
            await coll.create_index(spec["keys"], **kwargs)
    deps.set_db(database)
    from routers.contracts import router as contracts_router
    app = FastAPI()
    app.include_router(contracts_router, prefix="/api")

    async def fake_user():
        return {"id": "u-1", "email": "alice@gpi.com", "role": "admin"}
    app.dependency_overrides[get_current_user] = fake_user
    return app, database


# ---------------------------------------------------------------------------
# Tighter threshold telemetry — banded override rates
# ---------------------------------------------------------------------------

class TestBandedTelemetry:
    @pytest.mark.asyncio
    async def test_separates_auto_confirm_and_propose_overrides(
        self, app_db, configured_singleton,
    ):
        app, db = app_db
        now = datetime.now(timezone.utc).isoformat()
        # 4 system-emitted links: 2 auto_confirm-band, 2 propose-band.
        # Override pattern:
        #   - 1 of 2 auto_confirm rejected by human → 50% override there
        #   - 0 of 2 propose rejected → 0% override there
        await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_many([
            {"id": "L-A1", "agreement_id": "a", "link_type": "customer",
             "bc_entity": "customers", "bc_no": "C1", "match_method": "fuzzy",
             "confidence": 0.99, "status": "auto_confirmed", "linked_by": "system"},
            {"id": "L-A2", "agreement_id": "a", "link_type": "customer",
             "bc_entity": "customers", "bc_no": "C2", "match_method": "fuzzy",
             "confidence": 0.97, "status": "auto_confirmed", "linked_by": "system"},
            {"id": "L-P1", "agreement_id": "a", "link_type": "vendor",
             "bc_entity": "vendors", "bc_no": "V1", "match_method": "fuzzy",
             "confidence": 0.85, "status": "proposed", "linked_by": "system"},
            {"id": "L-P2", "agreement_id": "a", "link_type": "vendor",
             "bc_entity": "vendors", "bc_no": "V2", "match_method": "fuzzy",
             "confidence": 0.82, "status": "proposed", "linked_by": "system"},
        ])
        await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].insert_many([
            {"id": "au-1", "agreement_id": "a", "action": "proposed_link",
             "actor": "system", "link_id": "L-A1", "at": now},
            {"id": "au-2", "agreement_id": "a", "action": "proposed_link",
             "actor": "system", "link_id": "L-A2", "at": now},
            {"id": "au-3", "agreement_id": "a", "action": "proposed_link",
             "actor": "system", "link_id": "L-P1", "at": now},
            {"id": "au-4", "agreement_id": "a", "action": "proposed_link",
             "actor": "system", "link_id": "L-P2", "at": now},
            # Human rejects ONE auto-confirm link only.
            {"id": "au-5", "agreement_id": "a", "action": "rejected_link",
             "actor": "alice@gpi.com", "link_id": "L-A1", "at": now},
        ])

        c = TestClient(app)
        r = c.get("/api/contracts/threshold-telemetry", params={"days": 7})
        assert r.status_code == 200
        body = r.json()

        assert body["system_emitted"] == 4
        assert body["human_overrides"] == 1
        assert body["by_threshold_band"]["auto_confirm"] == 2
        assert body["by_threshold_band"]["propose"] == 2
        assert body["by_band_overrides"]["auto_confirm"] == 1
        assert body["by_band_overrides"]["propose"] == 0
        assert body["auto_confirm_override_rate"] == 0.5  # 1/2
        assert body["propose_override_rate"] == 0.0       # 0/2
        # Combined overall rate kept for back-compat:
        assert body["override_rate"] == 0.25              # 1/4

    @pytest.mark.asyncio
    async def test_empty_state(self, app_db, configured_singleton):
        app, _ = app_db
        c = TestClient(app)
        r = c.get("/api/contracts/threshold-telemetry", params={"days": 30})
        body = r.json()
        assert body["system_emitted"] == 0
        assert body["auto_confirm_override_rate"] == 0.0
        assert body["propose_override_rate"] == 0.0
        # Keys still present even with no data — UI relies on the shape.
        assert "by_band_overrides" in body
        assert body["by_band_overrides"]["auto_confirm"] == 0


# ---------------------------------------------------------------------------
# BC search (scoped to Contract Intelligence module)
# ---------------------------------------------------------------------------

class TestBCSearch:
    @pytest.mark.asyncio
    async def test_customer_search_by_name(self, app_db, configured_singleton):
        app, db = app_db
        await db["bc_reference_cache"].insert_many([
            {"bc_customer_no": "C-100", "bc_customer_name": "Acme Corporation",
             "bc_entity_type": "sales_order"},
            {"bc_customer_no": "C-100", "bc_customer_name": "Acme Corporation",
             "bc_entity_type": "sales_invoice"},  # dedupe target
            {"bc_customer_no": "C-200", "bc_customer_name": "Globex Industries",
             "bc_entity_type": "sales_order"},
            # Non-customer rows shouldn't show up
            {"bc_vendor_no": "V-9", "bc_vendor_name": "Acme Supplier"},
        ])
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "acme", "link_type": "customer"})
        assert r.status_code == 200
        body = r.json()
        nos = [m["bc_no"] for m in body["matches"]]
        assert "C-100" in nos
        assert "C-200" not in nos
        # Dedupe: C-100 only appears once
        assert nos.count("C-100") == 1

    @pytest.mark.asyncio
    async def test_customer_search_by_exact_no(self, app_db, configured_singleton):
        app, db = app_db
        await db["bc_reference_cache"].insert_one({
            "bc_customer_no": "C-300", "bc_customer_name": "Initech LLC",
            "bc_entity_type": "sales_order",
        })
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "C-300", "link_type": "customer"})
        body = r.json()
        assert any(m["bc_no"] == "C-300" for m in body["matches"])

    @pytest.mark.asyncio
    async def test_vendor_search_isolated_from_customer(
        self, app_db, configured_singleton,
    ):
        app, db = app_db
        await db["bc_reference_cache"].insert_many([
            {"bc_vendor_no": "V-1", "bc_vendor_name": "ShipFast Logistics",
             "bc_entity_type": "purchase_order"},
            {"bc_customer_no": "C-1", "bc_customer_name": "ShipFast Customer Co",
             "bc_entity_type": "sales_order"},
        ])
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "shipfast", "link_type": "vendor"})
        body = r.json()
        assert len(body["matches"]) == 1
        assert body["matches"][0]["bc_no"] == "V-1"

    @pytest.mark.asyncio
    async def test_item_returns_hint_and_empty(self, app_db, configured_singleton):
        app, _ = app_db
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "WIDGET", "link_type": "item"})
        body = r.json()
        assert body["matches"] == []
        assert "hint" in body
        assert "manual" in body["hint"].lower()

    @pytest.mark.asyncio
    async def test_invalid_link_type_rejected(self, app_db, configured_singleton):
        app, _ = app_db
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "anything", "link_type": "spaceship"})
        # FastAPI's regex constraint returns 422
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_regex_special_chars_escaped(self, app_db, configured_singleton):
        """User input containing regex meta-chars must not blow up the search."""
        app, db = app_db
        await db["bc_reference_cache"].insert_one({
            "bc_customer_no": "C-9", "bc_customer_name": "Star.Co (Plus++)",
            "bc_entity_type": "sales_order",
        })
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "(Plus++", "link_type": "customer"})
        # Should not 500; should not match (literal substring)
        assert r.status_code == 200
        # And a real substring search works:
        r2 = c.get("/api/contracts/bc-search",
                   params={"q": "Star.", "link_type": "customer"})
        body2 = r2.json()
        assert any(m["bc_no"] == "C-9" for m in body2["matches"])

    @pytest.mark.asyncio
    async def test_auth_required(self, app_db, configured_singleton):
        app, _ = app_db
        from services.auth_deps import get_current_user as real_dep
        app.dependency_overrides.pop(real_dep, None)
        c = TestClient(app)
        r = c.get("/api/contracts/bc-search",
                  params={"q": "x", "link_type": "vendor"})
        assert r.status_code == 401
