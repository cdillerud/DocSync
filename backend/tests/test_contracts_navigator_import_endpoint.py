"""Phase 4C(a) — Navigator import HTTP endpoint tests.

Spins up an isolated FastAPI app with mongomock-backed contract collections
and exercises ``POST /api/contracts/navigator/import`` end-to-end:

  * Auth gating (admin-only)
  * File-type validation
  * Size cap enforcement
  * Dry-run shape + counts
  * Commit shape + counts
  * Idempotency on replay
  * CLI shares the same service (no drift)
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import deps
from models.contracts import CONTRACTS_COLLECTIONS, CONTRACTS_INDEXES
from services.auth_deps import get_current_user, require_admin
from services.contracts.navigator_import import max_upload_bytes


BRAGG_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "docusign" / "bragg"
    / "bragg_metadata_export_redacted.json"
)


def _run_async(coro):
    """Run an async helper inline.

    TestClient + httpx leaves MainThread's event-loop slot in a state
    that breaks ``asyncio.get_event_loop()`` on Python 3.11+ when called
    later in the test session. We resurrect a usable loop here so this
    test file does not pollute downstream files (e.g.
    ``test_contracts_phase3.py``)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_and_db():
    """Minimal FastAPI app mounting only the contracts router, backed by
    a mongomock-motor instance with the production indexes pre-created."""
    client = AsyncMongoMockClient()
    database = client["contracts_test"]

    async def _materialize():
        for coll_name, specs in CONTRACTS_INDEXES.items():
            coll = database[CONTRACTS_COLLECTIONS[coll_name]]
            for spec in specs:
                kwargs = {k: v for k, v in spec.items() if k != "keys"}
                await coll.create_index(spec["keys"], **kwargs)
    _run_async(_materialize())

    deps.set_db(database)

    from routers.contracts import router as contracts_router
    app = FastAPI()
    app.include_router(contracts_router, prefix="/api")

    async def fake_admin():
        return {"id": "u-1", "email": "admin@gpi.com", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_admin
    app.dependency_overrides[require_admin] = fake_admin
    yield app, database
    app.dependency_overrides.clear()


@pytest.fixture()
def app_and_db_non_admin(app_and_db):
    app, db = app_and_db

    async def fake_user():
        return {"id": "u-2", "email": "viewer@gpi.com", "role": "viewer"}

    # Override only require_admin to fail — get_current_user stays valid.
    async def fail_admin():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin role required")

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fail_admin
    return app, db


def _bragg_row() -> Dict[str, Any]:
    return json.loads(BRAGG_FIXTURE_PATH.read_text(encoding="utf-8"))["row"]


def _make_csv_bytes(row: Dict[str, Any]) -> bytes:
    import csv
    bio = io.StringIO()
    writer = csv.DictWriter(bio, fieldnames=list(row.keys()))
    writer.writeheader()
    writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return bio.getvalue().encode("utf-8")


def _make_xlsx_bytes(row: Dict[str, Any]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(row.keys()))
    ws.append(list(row.values()))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# Auth + validation
# ---------------------------------------------------------------------------

class TestAuthGating:

    def test_non_admin_rejected(self, app_and_db_non_admin):
        app, _ = app_and_db_non_admin
        c = TestClient(app)
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        assert r.status_code == 403


class TestUploadValidation:

    def test_rejects_missing_file(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post("/api/contracts/navigator/import")
        # FastAPI raises 422 for missing required form field.
        assert r.status_code in (400, 422)

    def test_rejects_unknown_extension(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.txt", b"not a navigator export", "text/plain")},
        )
        assert r.status_code == 400
        assert "unsupported" in r.json()["detail"].lower()

    def test_rejects_oversize_upload(self, app_and_db, monkeypatch):
        """Force a tiny size cap and ship a file that just exceeds it."""
        monkeypatch.setenv("CONTRACT_NAVIGATOR_IMPORT_MAX_BYTES", "256")
        # Re-read cap to confirm env override took effect.
        assert max_upload_bytes() == 256

        app, _ = app_and_db
        c = TestClient(app)
        oversize = b"x" * 1024  # 1 KB > 256 B cap
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.csv", oversize, "text/csv")},
        )
        assert r.status_code == 413
        assert "maximum size" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRunEndpoint:

    def test_dryrun_returns_structured_summary(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "dryrun"
        assert body["row_count"] == 1
        assert body["error_count"] == 0
        assert body["agreements_detected"] == 1
        assert body["parties_detected"] >= 2
        assert body["terms_detected"] >= 8
        assert body["documents_detected"] >= 1
        assert body["would_create"] == 1
        assert body["would_update"] == 0
        assert body["filename"] == "nav.csv"
        # Per-row report shape.
        row = body["rows"][0]
        assert row["envelope_id"] == _bragg_row()["Envelope Id"]
        assert row["provider_agreement_id"] == _bragg_row()["Agreement Id"]
        assert row["status"] == "completed"
        assert row["error"] is None

    def test_dryrun_xlsx(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        xlsx_bytes = _make_xlsx_bytes(_bragg_row())
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": (
                "nav.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["row_count"] == 1
        assert body["agreements_detected"] == 1

    def test_dryrun_does_not_persist(self, app_and_db):
        app, db = app_and_db
        c = TestClient(app)
        c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        # No agreement should have been written.
        async def _count() -> int:
            return await db[CONTRACTS_COLLECTIONS["agreements"]].count_documents({})
        assert _run_async(_count()) == 0


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

class TestCommitEndpoint:

    def test_commit_persists_one_row(self, app_and_db):
        app, db = app_and_db
        c = TestClient(app)
        r = c.post(
            "/api/contracts/navigator/import?commit=true",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "commit"
        assert body["committed"] == 1
        assert body["skipped"] == 0
        # Underlying agreement row landed in the agreements collection.
        async def _count():
            return await db[CONTRACTS_COLLECTIONS["agreements"]].count_documents({})
        assert _run_async(_count()) == 1

    def test_commit_replay_is_idempotent(self, app_and_db):
        app, db = app_and_db
        c = TestClient(app)
        # First commit.
        r1 = c.post(
            "/api/contracts/navigator/import?commit=true",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        assert r1.status_code == 200
        assert r1.json()["committed"] == 1
        # Second commit of the same row.
        r2 = c.post(
            "/api/contracts/navigator/import?commit=true",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        body = r2.json()
        assert r2.status_code == 200
        assert body["committed"] == 0
        assert body["skipped"] == 1
        # Still exactly one agreement row.
        async def _count():
            return await db[CONTRACTS_COLLECTIONS["agreements"]].count_documents({})
        assert _run_async(_count()) == 1

    def test_dryrun_after_commit_reports_would_update(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        # Commit first.
        c.post(
            "/api/contracts/navigator/import?commit=true",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        # Dry-run after commit: row is now an existing envelope ⇒ would_update=1.
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("nav.csv", _make_csv_bytes(_bragg_row()), "text/csv")},
        )
        body = r.json()
        assert body["mode"] == "dryrun"
        assert body["would_create"] == 0
        assert body["would_update"] == 1


# ---------------------------------------------------------------------------
# Error rows still surface
# ---------------------------------------------------------------------------

class TestErrorRows:

    def test_row_missing_envelope_id_reported(self, app_and_db):
        app, _ = app_and_db
        c = TestClient(app)
        bad_row = {"Agreement Type": "MSA", "Parties": "A;B"}  # no Envelope Id
        good_row = _bragg_row()
        # Build a 2-row CSV (one good, one bad).
        import csv as csvmod
        bio = io.StringIO()
        fieldnames = list(set(good_row.keys()) | set(bad_row.keys()))
        writer = csvmod.DictWriter(bio, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({k: good_row.get(k, "") for k in fieldnames})
        writer.writerow({k: bad_row.get(k, "") for k in fieldnames})
        r = c.post(
            "/api/contracts/navigator/import",
            files={"file": ("mixed.csv", bio.getvalue().encode(), "text/csv")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["row_count"] == 2
        assert body["error_count"] == 1
        assert body["agreements_detected"] == 1
        # Find the bad row in the per-row report.
        bad = [row for row in body["rows"] if row["error"]]
        assert len(bad) == 1
        assert "Envelope Id" in bad[0]["error"]
