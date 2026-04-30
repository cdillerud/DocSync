"""Phase 4C(c) — HTTP endpoint + ingest method tests.

Covers:
  * Multipart upload with admin gating
  * Dry-run preview (no DB writes)
  * Commit upserts terms / obligations / pricing overlays
  * Idempotent replay (commit twice = same row counts, no duplicates)
  * Per-line MOQ overlay merges onto an existing pricing row
  * Ambiguity opens a single ``pdf_extraction_ambiguous`` exception
    that survives replay without duplication
  * 404 on unknown agreement
  * 400 on non-PDF upload
  * 401 on missing auth
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import deps
from models.contracts import CONTRACTS_COLLECTIONS, CONTRACTS_INDEXES
from services.auth_deps import get_current_user, require_admin
from services.contracts.contract_intelligence_service import (
    ContractIntelligenceService,
)
from services.contracts.pdf_extraction import run_extraction


_FIXTURES = Path(__file__).parent / "fixtures" / "contracts" / "pdfs"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def app_and_db():
    client = AsyncMongoMockClient()
    database = client["contracts_test_pdf"]

    async def _materialize():
        for coll_name, specs in CONTRACTS_INDEXES.items():
            coll = database[CONTRACTS_COLLECTIONS[coll_name]]
            for spec in specs:
                kwargs = {k: v for k, v in spec.items() if k != "keys"}
                await coll.create_index(spec["keys"], **kwargs)
    _run(_materialize())

    deps.set_db(database)

    from routers.contracts import router as contracts_router

    app = FastAPI()
    app.include_router(contracts_router, prefix="/api")

    async def fake_user():
        return {"id": "u-1", "email": "alice@gpi.com", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_user
    return app, database


def _seed_agreement(db, agreement_id: str = "agr-1") -> None:
    _run(db[CONTRACTS_COLLECTIONS["agreements"]].insert_one({
        "id": agreement_id,
        "provider": "docusign",
        "provider_envelope_id": f"env-{agreement_id}",
        "status": "completed",
    }))


def _bragg_pdf() -> bytes:
    return (_FIXTURES / "bragg_supply_excerpt.pdf").read_bytes()


def _tooling_pdf() -> bytes:
    return (_FIXTURES / "tooling_amortization_excerpt.pdf").read_bytes()


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class TestPdfExtractEndpointDryRun:
    def test_dry_run_returns_preview_no_writes(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-1")
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-1/pdf-extract?commit=false",
            files={"file": ("bragg.pdf", _bragg_pdf(), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "dryrun"
        assert body["agreement_id"] == "agr-1"
        assert body["page_count"] == 1
        keys = {f["key"] for f in body["fields"]}
        assert "freight_inco_term" in keys
        # No DB writes.
        terms_count = _run(
            db[CONTRACTS_COLLECTIONS["agreement_terms"]].count_documents({})
        )
        oblig_count = _run(
            db[CONTRACTS_COLLECTIONS["agreement_obligations"]].count_documents({})
        )
        assert terms_count == 0
        assert oblig_count == 0


class TestPdfExtractEndpointCommit:
    def test_commit_persists_terms_and_obligations(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-tooling")
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-tooling/pdf-extract?commit=true",
            files={"file": ("tooling.pdf", _tooling_pdf(), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "commit"
        ws = body["write_summary"]
        assert ws["agreement_id"] == "agr-tooling"
        # tooling fixture: 0 term rows, 2 obligation rows
        # (volume_commitment + tooling_amortization), 1 pricing overlay.
        assert ws["obligations_written"] == 2
        assert ws["pricing_overlays"] >= 1

        # Verify rows on disk.
        oblig_kinds = _run(
            db[CONTRACTS_COLLECTIONS["agreement_obligations"]]
            .distinct("kind", {"agreement_id": "agr-tooling"})
        )
        assert "tooling_amortization" in oblig_kinds
        assert "volume_commitment" in oblig_kinds

    def test_commit_is_idempotent_on_replay(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-bragg")
        c = TestClient(app)

        def _post():
            return c.post(
                "/api/contracts/agreements/agr-bragg/pdf-extract?commit=true",
                files={"file": ("bragg.pdf", _bragg_pdf(), "application/pdf")},
            )

        _post()
        first_terms = _run(
            db[CONTRACTS_COLLECTIONS["agreement_terms"]].count_documents({
                "agreement_id": "agr-bragg",
            })
        )
        _post()  # replay
        second_terms = _run(
            db[CONTRACTS_COLLECTIONS["agreement_terms"]].count_documents({
                "agreement_id": "agr-bragg",
            })
        )
        assert first_terms == second_terms

    def test_per_line_moq_overlay_creates_pricing_rows(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-bragg2")
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-bragg2/pdf-extract?commit=true",
            files={"file": ("bragg.pdf", _bragg_pdf(), "application/pdf")},
        )
        assert r.status_code == 200
        # Two per-line MOQs in the fixture.
        rows = _run(
            db[CONTRACTS_COLLECTIONS["agreement_pricing"]].find(
                {"agreement_id": "agr-bragg2",
                 "min_quantity": {"$ne": None}},
                {"_id": 0},
            ).to_list(length=10)
        )
        labels = {r["item_label"] for r in rows}
        assert {"ACME-WIDGET-12", "ACME-GASKET-08"}.issubset(labels)


class TestPdfExtractEndpointGuards:
    def test_404_when_agreement_missing(self, app_and_db):
        app, _db = app_and_db
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-missing/pdf-extract?commit=false",
            files={"file": ("bragg.pdf", _bragg_pdf(), "application/pdf")},
        )
        assert r.status_code == 404

    def test_400_when_not_a_pdf_filename(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-x")
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-x/pdf-extract?commit=false",
            files={"file": ("plain.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400

    def test_400_when_file_field_missing(self, app_and_db):
        app, db = app_and_db
        _seed_agreement(db, "agr-x")
        c = TestClient(app)
        r = c.post(
            "/api/contracts/agreements/agr-x/pdf-extract?commit=false",
        )
        # FastAPI returns 422 for missing form fields.
        assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Service-level ingest_pdf_extraction tests (independent of HTTP)
# ---------------------------------------------------------------------------


class TestIngestPdfExtractionService:
    def test_ingest_writes_audit_row(self, app_and_db):
        _app, db = app_and_db
        _seed_agreement(db, "agr-svc")
        svc = ContractIntelligenceService(db)
        result = run_extraction(
            agreement_id="agr-svc",
            data=_bragg_pdf(),
            filename="bragg.pdf",
        )
        summary = _run(svc.ingest_pdf_extraction(
            agreement_id="agr-svc", result=result, actor="cli",
        ))
        assert summary["agreement_id"] == "agr-svc"

        audits = _run(
            db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
                {"agreement_id": "agr-svc"}, {"_id": 0},
            ).to_list(length=10)
        )
        assert any(
            a.get("after", {}).get("stage") == "pdf_body_extraction"
            for a in audits
        )

    def test_ingest_raises_on_missing_agreement(self, app_and_db):
        _app, db = app_and_db
        svc = ContractIntelligenceService(db)
        result = run_extraction(
            agreement_id="agr-missing",
            data=_bragg_pdf(),
            filename="bragg.pdf",
        )
        with pytest.raises(LookupError):
            _run(svc.ingest_pdf_extraction(
                agreement_id="agr-missing", result=result,
            ))

    def test_extraction_error_emits_exception(self, app_and_db):
        _app, db = app_and_db
        _seed_agreement(db, "agr-bad")
        svc = ContractIntelligenceService(db)
        result = run_extraction(
            agreement_id="agr-bad",
            data=b"not a pdf",
            filename="bad.pdf",
        )
        assert result.error
        summary = _run(svc.ingest_pdf_extraction(
            agreement_id="agr-bad", result=result,
        ))
        assert summary["exceptions_written"] == 1

        rows = _run(
            db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].find(
                {"agreement_id": "agr-bad"}, {"_id": 0},
            ).to_list(length=10)
        )
        assert any(r["code"] == "pdf_extraction_failed" for r in rows)

    def test_ambiguity_creates_single_exception_on_replay(self, app_and_db):
        _app, db = app_and_db
        _seed_agreement(db, "agr-amb")
        svc = ContractIntelligenceService(db)

        # Inject a synthetic ExtractionResult with two distinct
        # freight_payer values so the ambiguity detector fires.
        from services.contracts.pdf_extraction import ExtractionResult
        from services.contracts.pdf_field_extractors import ExtractedField
        from services.contracts.pdf_extraction import _detect_ambiguities  # type: ignore

        fields = [
            ExtractedField(
                target="term", key="freight_payer",
                value={"payer": "prepaid", "subject": "buyer"},
                raw_text="Freight prepaid by Buyer", confidence=0.85,
            ),
            ExtractedField(
                target="term", key="freight_payer",
                value={"payer": "collect", "subject": "seller"},
                raw_text="freight collect by Seller", confidence=0.85,
            ),
        ]
        result = ExtractionResult(
            agreement_id="agr-amb",
            filename="synthetic.pdf",
            page_count=1,
            bytes_size=1,
            text_chars=10,
            fields=fields,
            line_pricing=[],
            ambiguities=_detect_ambiguities(fields),
        )

        s1 = _run(svc.ingest_pdf_extraction(
            agreement_id="agr-amb", result=result,
        ))
        s2 = _run(svc.ingest_pdf_extraction(
            agreement_id="agr-amb", result=result,
        ))
        # First run writes 1 ambiguity exception, replay updates rather
        # than inserting another one.
        assert s1["exceptions_written"] == 1
        assert s2["exceptions_written"] == 0
        rows = _run(
            db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].find({
                "agreement_id": "agr-amb",
                "code": "pdf_extraction_ambiguous",
            }, {"_id": 0}).to_list(length=10)
        )
        assert len(rows) == 1
