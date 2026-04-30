"""Phase 2 — DocuSign webhook + manual-mapping HTTP endpoints (TestClient).

Covers:
  * Webhook posture when not configured (503)
  * Webhook signature validation (401 on tampering, 200 on valid)
  * Webhook idempotency over HTTP (replay returns duplicate=True)
  * Background processing wiring (event row marked processed)
  * Auth gating on read/write endpoints (401 without bearer)
  * Manual link / confirm / reject / resolve_exception via HTTP
  * /contracts/health diagnostic surface

Run:
    cd /app/backend && python -m pytest tests/test_contracts_endpoints.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any, Dict

import pytest
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


def _run(coro):
    """Run a coroutine in a fresh event loop.

    Replaces ``asyncio.get_event_loop().run_until_complete(...)`` which
    raises ``RuntimeError`` on Python 3.10+ once any earlier test has
    closed the default loop.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

@pytest.fixture()
def configured_singleton(monkeypatch):
    """Force the module singleton to a configured client (HMAC ready)."""
    reset_docusign_client_for_tests()
    settings = DocuSignSettings(
        integration_key="ik", user_id="uid", account_id="acc",
        oauth_host="account-d.docusign.com",
        hmac_secrets=("phase2-secret",),
    )
    client = DocuSignClient(settings)
    monkeypatch.setattr(ds_module, "_singleton", client)
    yield client
    reset_docusign_client_for_tests()


@pytest.fixture()
def unconfigured_singleton(monkeypatch):
    reset_docusign_client_for_tests()
    client = DocuSignClient(DocuSignSettings())  # no secrets
    monkeypatch.setattr(ds_module, "_singleton", client)
    yield client
    reset_docusign_client_for_tests()


@pytest.fixture()
def app_and_db():
    """Build a minimal FastAPI app mounting only the contracts router.

    The same `db` Motor handle is wired into `deps.set_db()` so the router's
    `get_db()` returns the in-memory mongomock instance, with the production
    indexes pre-created so unique-key idempotency actually fires.
    """
    client = AsyncMongoMockClient()
    database = client["contracts_test"]

    # Materialize indexes synchronously for the test session.
    # Use a fresh event loop instead of asyncio.get_event_loop() — the
    # latter raises RuntimeError on Python 3.10+ if a previous test in
    # the run has already closed the default loop.
    async def _materialize():
        for coll_name, specs in CONTRACTS_INDEXES.items():
            coll = database[CONTRACTS_COLLECTIONS[coll_name]]
            for spec in specs:
                kwargs = {k: v for k, v in spec.items() if k != "keys"}
                await coll.create_index(spec["keys"], **kwargs)
    _run(_materialize())

    deps.set_db(database)

    # Defer router import until after deps wiring.
    from routers.contracts import router as contracts_router

    app = FastAPI()
    app.include_router(contracts_router, prefix="/api")

    # Bypass auth in tests: get_current_user → fixed user dict.
    async def fake_user():
        return {"id": "u-1", "email": "alice@gpi.com", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, database


def _sign(body: bytes, secret: str = "phase2-secret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(envelope_id="env-1234", event_id="evt-1") -> Dict[str, Any]:
    return {
        "event": "envelope-completed",
        "eventId": event_id,
        "data": {
            "envelopeId": envelope_id,
            "envelopeSummary": {
                "envelopeId": envelope_id,
                "status": "completed",
                "subject": "Test MSA",
                "completedDateTime": "2026-04-29T18:55:30Z",
                "sender": {"userName": "Sue", "email": "sue@gpi.com"},
                "recipients": {
                    "signers": [{
                        "recipientId": "1", "name": "Alice", "email": "a@acme.com",
                        "companyName": "Acme Co", "status": "completed",
                    }]
                },
                "envelopeDocuments": [{"documentId": "1", "name": "msa.pdf"}],
                "customFields": {"textCustomFields": []},
                "formData": [],
            },
        },
    }


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------

class TestWebhookSecurity:
    def test_503_when_not_configured(self, app_and_db, unconfigured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post("/api/docusign/webhook", json=_payload())
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"].lower()

    def test_401_when_signature_missing(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        body = json.dumps(_payload()).encode()
        r = c.post("/api/docusign/webhook", content=body,
                   headers={"content-type": "application/json"})
        assert r.status_code == 401

    def test_401_when_signature_tampered(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        body = json.dumps(_payload()).encode()
        r = c.post(
            "/api/docusign/webhook", content=body,
            headers={
                "content-type": "application/json",
                "x-docusign-signature-1": "deadbeef",
            },
        )
        assert r.status_code == 401

    def test_400_when_body_malformed(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        body = b"not-json{"
        sig = _sign(body)
        r = c.post(
            "/api/docusign/webhook", content=body,
            headers={
                "content-type": "application/json",
                "x-docusign-signature-1": sig,
            },
        )
        assert r.status_code == 400

    def test_200_when_signature_valid(self, app_and_db, configured_singleton):
        app, db = app_and_db
        c = TestClient(app)
        body = json.dumps(_payload()).encode()
        sig = _sign(body)
        r = c.post(
            "/api/docusign/webhook", content=body,
            headers={
                "content-type": "application/json",
                "x-docusign-signature-1": sig,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["acknowledged"] is True
        assert data["duplicate"] is False
        # Event row exists
        async def _check():
            return await db[CONTRACTS_COLLECTIONS["agreement_events"]].find_one(
                {"provider_event_id": "evt-1"}, {"_id": 0},
            )
        evt = _run(_check())
        assert evt is not None
        assert evt["hmac_valid"] is True

    def test_replay_acks_duplicate_without_double_processing(
        self, app_and_db, configured_singleton,
    ):
        app, db = app_and_db
        c = TestClient(app)
        body = json.dumps(_payload(event_id="evt-replay")).encode()
        sig = _sign(body)
        headers = {
            "content-type": "application/json",
            "x-docusign-signature-1": sig,
        }

        first = c.post("/api/docusign/webhook", content=body, headers=headers)
        second = c.post("/api/docusign/webhook", content=body, headers=headers)
        assert first.status_code == 200 and first.json()["duplicate"] is False
        assert second.status_code == 200 and second.json()["duplicate"] is True

        async def _count():
            return await db[CONTRACTS_COLLECTIONS["agreement_events"]].count_documents(
                {"provider_event_id": "evt-replay"},
            )
        n = _run(_count())
        assert n == 1


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

class TestReadEndpoints:
    def test_health(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.get("/api/contracts/health")
        assert r.status_code == 200
        body = r.json()
        assert body["module"] == "contract_intelligence"
        assert body["docusign"]["webhook_ready"] is True

    def test_list_agreements_empty(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.get("/api/contracts/agreements")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_get_agreement_404(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.get("/api/contracts/agreements/nope")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Manual mapping endpoints
# ---------------------------------------------------------------------------

class TestManualEndpoints:
    def test_create_manual_link_404_for_missing_agreement(
        self, app_and_db, configured_singleton,
    ):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/missing/links",
            json={"link_type": "customer", "bc_entity": "customers", "bc_no": "C-1"},
        )
        assert r.status_code == 404

    def test_full_manual_flow(self, app_and_db, configured_singleton):
        app, db = app_and_db
        c = TestClient(app)

        # Seed an agreement directly via Motor
        async def _seed():
            await db[CONTRACTS_COLLECTIONS["agreements"]].insert_one({
                "id": "agr-X", "provider": "docusign",
                "provider_envelope_id": "env-X", "status": "sent",
            })
        _run(_seed())

        # Create manual link
        r = c.post(
            "/api/contracts/agreements/agr-X/links",
            json={
                "link_type": "vendor", "bc_entity": "vendors",
                "bc_no": "V-9", "bc_name_snapshot": "Manual Vendor",
                "notes": "verified",
            },
        )
        assert r.status_code == 200, r.text
        link_id = r.json()["link"]["id"]
        assert r.json()["link"]["status"] == "confirmed"

        # Reject (should flip status to rejected)
        r = c.post(
            f"/api/contracts/agreements/agr-X/links/{link_id}/reject",
            json={"notes": "wrong row"},
        )
        assert r.status_code == 200
        assert r.json()["link"]["status"] == "rejected"
        assert r.json()["link"]["notes"] == "wrong row"

        # Confirm a different proposed link
        async def _seed_proposed():
            await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_one({
                "id": "link-prop", "agreement_id": "agr-X",
                "link_type": "customer", "bc_entity": "customers",
                "bc_no": "C-7", "match_method": "fuzzy",
                "confidence": 0.85, "status": "proposed",
                "linked_by": "system",
            })
        _run(_seed_proposed())

        r = c.post("/api/contracts/agreements/agr-X/links/link-prop/confirm")
        assert r.status_code == 200
        assert r.json()["link"]["status"] == "confirmed"
        assert r.json()["link"]["confirmed_by"] == "alice@gpi.com"

    def test_resolve_exception(self, app_and_db, configured_singleton):
        app, db = app_and_db
        c = TestClient(app)

        async def _seed():
            await db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].insert_one({
                "id": "ex-99", "agreement_id": "agr-X",
                "code": "party_unmatched", "severity": "medium",
                "details": {}, "status": "open",
            })
        _run(_seed())

        r = c.post("/api/contracts/exceptions/ex-99/resolve",
                   json={"note": "added to BC"})
        assert r.status_code == 200
        body = r.json()["exception"]
        assert body["status"] == "resolved"
        assert body["resolved_by"] == "alice@gpi.com"
        assert body["resolution_note"] == "added to BC"

    def test_resolve_exception_404(self, app_and_db, configured_singleton):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post("/api/contracts/exceptions/missing/resolve")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

class TestAuthGating:
    def test_endpoints_require_auth(self, app_and_db, configured_singleton):
        # Build a SECOND app where get_current_user is NOT overridden.
        app, _ = app_and_db
        # Drop the test override so the real dependency runs.
        from services.auth_deps import get_current_user as real_dep
        app.dependency_overrides.pop(real_dep, None)
        c = TestClient(app)

        # Without token, every authenticated route should 401
        for path in (
            "/api/contracts/agreements",
            "/api/contracts/agreements/anything",
            "/api/contracts/exceptions",
        ):
            r = c.get(path)
            assert r.status_code == 401, path
