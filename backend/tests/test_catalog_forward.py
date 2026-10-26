"""
Tests for services/catalog_forward.py — forwarding newly ingested supplier
pricing documents (price lists, supplier quotes, price-increase letters,
stock lists) to the Commercial AI catalog inbox.

Pins down:
  1. qualification: supplier pricing qualifies; AP invoices, statements,
     Gamer's own QUO- quotes, page-split copies and internal senders without
     a supplier do not;
  2. off by default, and the hook does nothing while disabled;
  3. dry run decides and records but never sends;
  4. one submit per source email, nothing sent twice;
  5. a failing POST is recorded and never raises into ingestion;
  6. the intake key never lands in the stored records.
"""
import asyncio

import httpx
import mongomock_motor
import pytest

from services import catalog_forward as cf

KEY = "secret-intake-key-123"
URL = "https://catalog.example.test/api/v70/catalog/intake/submit"


def _doc(doc_id="d1", **overrides):
    doc = {
        "id": doc_id,
        "file_name": "Pretium price list Nov 2026.xlsx",
        "email_subject": "Updated pricing",
        "email_sender": "rep@pretiumpkg.com",
        "email_id": "msg-1",
        "document_type": "Unknown_Document",
        "doc_type": "OTHER",
        "category": "Other",
        "vendor_raw": "Pretium Packaging",
        "file_size": 2048,
        "created_utc": "2026-10-21T12:00:00+00:00",
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def fake_db(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["test_catalog_forward"]
    monkeypatch.setattr(cf, "get_db", lambda: db)
    return db


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CATALOG_FORWARD_ENABLED", "true")
    monkeypatch.setenv("CATALOG_FORWARD_URL", URL)
    monkeypatch.setenv("CATALOG_FORWARD_KEY", KEY)
    monkeypatch.delenv("CATALOG_FORWARD_DRY_RUN", raising=False)


@pytest.fixture
def fake_bytes(monkeypatch):
    async def _load(doc):
        return b"bytes of " + doc["id"].encode()
    monkeypatch.setattr(cf, "load_document_bytes", _load)


@pytest.fixture
def posts(monkeypatch):
    sent = []

    async def _post(settings, payload):
        sent.append({"key": settings.key, "url": settings.url, "payload": payload})
        return {"status": "ACCEPTED", "id": f"intake-{len(sent)}"}

    monkeypatch.setattr(cf, "_post_submit", _post)
    return sent


# ──────────────────────────────────────────────────────────────
# Qualification
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("overrides, expected", [
    ({}, "supplier_pricing:price_list"),
    ({"file_name": "Quote_26092338_0_29-09-2026.pdf", "document_type": "Sales_Quote"}, "supplier_pricing:quote"),
    ({"file_name": "Price Increase Letter Jan 2027.pdf", "email_subject": "Notice"}, "supplier_pricing:price_increase"),
    ({"file_name": "Resin surcharge Q4.pdf"}, "supplier_pricing:surcharge"),
    ({"file_name": "Shelf stock 10-20.xlsx", "document_type": "Inventory_Report"}, "supplier_pricing:stock_list"),
    ({"file_name": "open_inventory_report.csv"}, "supplier_pricing:open_inventory"),
    ({"file_name": "RFQ response 4471.pdf"}, "supplier_pricing:rfq_response"),
    ({"file_name": "Weekly availability.xlsm"}, "supplier_pricing:availability"),
    # Pricing word only in the subject still counts.
    ({"file_name": "attachment 1.pdf", "email_subject": "Quotation for 16oz jars"}, "supplier_pricing:quote"),
    # Forwarded by Gamer staff, but the document's vendor is a supplier.
    ({"email_sender": "buyer@gamerpackaging.com"}, "supplier_pricing:price_list"),
    # Outlook / eml attachments are accepted by the inbox too.
    ({"file_name": "FW Pricing.msg"}, "supplier_pricing:price_list"),
])
def test_qualifies(overrides, expected):
    assert cf.evaluate_document(_doc(**overrides)) == (True, expected)


@pytest.mark.parametrize("overrides, reason", [
    ({"file_name": "INV-88123.pdf", "document_type": "AP_Invoice", "doc_type": "AP_INVOICE"}, "excluded_type:AP_Invoice"),
    # Invoice wording in the name beats a pricing word.
    ({"file_name": "Invoice 88123 price adjustment.pdf"}, "looks_like_invoice"),
    ({"file_name": "Statement Oct 2026.pdf", "document_type": "Statement"}, "excluded_type:Statement"),
    ({"file_name": "Remittance advice.pdf", "document_type": "Remittance"}, "excluded_type:Remittance"),
    ({"file_name": "PO 4500123 pricing.pdf"}, "looks_like_purchase_order"),
    ({"file_name": "Customer PO.pdf", "document_type": "Sales_PO"}, "excluded_type:Sales_PO"),
    ({"doc_type": "PURCHASE_ORDER"}, "excluded_type:PURCHASE_ORDER"),
    # Gamer's own Spiro quote to a customer.
    ({"file_name": "QUO-1234-Johnson Foods.pdf", "document_type": "Sales_Quote"}, "gamer_quote_to_customer"),
    ({"file_name": "quote.pdf", "email_subject": "RE: QUO-5521- 16oz jars"}, "gamer_quote_to_customer"),
    # Gamer letterhead (vendor read from the document is Gamer).
    ({"file_name": "Quote 7781.pdf", "vendor_raw": "Gamer Packaging, Inc."}, "gamer_letterhead"),
    # Page-split copies.
    ({"file_name": "Pretium price list_doc1.pdf"}, "page_split_copy"),
    ({"parent_document_id": "parent-1"}, "page_split_copy"),
    # Internal sender and no supplier on the document.
    ({"email_sender": "chad@gamerpackaging.com", "vendor_raw": None}, "internal_sender_no_supplier"),
    ({"email_sender": None, "vendor_raw": None}, "no_supplier_signal"),
    ({"file_name": "scan0001.pdf", "email_subject": "Documents"}, "no_pricing_signal"),
    ({"file_name": "price list.xls"}, "unsupported_file_type:.xls"),
    ({"file_size": 16 * 1024 * 1024}, "file_too_large"),
    ({"catalog_forwarded_utc": "2026-10-20T00:00:00+00:00"}, "already_forwarded"),
])
def test_excluded(overrides, reason):
    assert cf.evaluate_document(_doc(**overrides)) == (False, reason)


# ──────────────────────────────────────────────────────────────
# Settings / disabled by default
# ──────────────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    for name in ("CATALOG_FORWARD_ENABLED", "CATALOG_FORWARD_URL", "CATALOG_FORWARD_KEY", "CATALOG_FORWARD_DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    s = cf.get_settings()
    assert s.enabled is False and s.dry_run is False
    assert s.public()["key_configured"] is False


@pytest.mark.asyncio
async def test_disabled_sends_and_records_nothing(monkeypatch, fake_db, fake_bytes, posts):
    monkeypatch.delenv("CATALOG_FORWARD_ENABLED", raising=False)
    await fake_db.hub_documents.insert_one(_doc())
    summary = await cf.forward_documents(["d1"])
    assert summary["reason"] == "disabled"
    assert posts == []
    stored = await fake_db.hub_documents.find_one({"id": "d1"})
    assert "catalog_forward" not in stored
    assert await fake_db[cf.LOG_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_hook_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("CATALOG_FORWARD_ENABLED", raising=False)
    called = []

    async def _boom(ids):
        called.append(ids)

    monkeypatch.setattr(cf, "forward_documents_safely", _boom)
    cf.schedule_forward_for_email(["d1"])
    await asyncio.sleep(0)
    assert called == []


# ──────────────────────────────────────────────────────────────
# Dry run
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_sends_nothing(monkeypatch, enabled, fake_db, fake_bytes, posts):
    monkeypatch.setenv("CATALOG_FORWARD_DRY_RUN", "true")
    await fake_db.hub_documents.insert_many([
        _doc("d1"),
        _doc("d2", file_name="INV-1.pdf", document_type="AP_Invoice", doc_type="AP_INVOICE"),
    ])
    summary = await cf.forward_documents(["d1", "d2"])
    assert posts == []
    assert summary["qualified"] == 1 and summary["skipped"] == 1
    d1 = await fake_db.hub_documents.find_one({"id": "d1"})
    assert d1["catalog_forward"]["status"] == "dry_run"
    assert not d1.get("catalog_forwarded_utc")
    d2 = await fake_db.hub_documents.find_one({"id": "d2"})
    assert d2["catalog_forward"] == {**d2["catalog_forward"], "status": "skipped", "reason": "excluded_type:AP_Invoice"}


# ──────────────────────────────────────────────────────────────
# Sending, batching, dedupe
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_submit_per_email_and_never_twice(enabled, fake_db, fake_bytes, posts):
    await fake_db.hub_documents.insert_many([
        _doc("d1", email_id="msg-1"),
        _doc("d2", email_id="msg-1", file_name="Pretium quote 7781.pdf"),
        _doc("d3", email_id="msg-1", file_name="Pretium price list_doc1.pdf"),  # page split: left out
        _doc("d4", email_id="msg-2", file_name="Berlin stock list.csv", vendor_raw="Berlin Packaging"),
    ])
    await cf.forward_documents(["d1", "d2", "d3", "d4"])

    assert len(posts) == 2
    by_email = {tuple(sorted(f["name"] for f in p["payload"]["files"])) for p in posts}
    assert by_email == {
        ("Pretium price list Nov 2026.xlsx", "Pretium quote 7781.pdf"),
        ("Berlin stock list.csv",),
    }
    first = posts[0]
    assert first["key"] == KEY and first["url"] == URL
    assert set(first["payload"]) == {"subject", "sender", "files", "note"}
    assert first["payload"]["subject"] == "Updated pricing"
    assert first["payload"]["sender"] == "rep@pretiumpkg.com"

    for doc_id in ("d1", "d2", "d4"):
        doc = await fake_db.hub_documents.find_one({"id": doc_id})
        assert doc["catalog_forwarded_utc"]
        assert doc["catalog_forward"]["status"] == "sent"

    # Same ids again (e.g. a re-poll or a content-hash duplicate): nothing new is sent.
    await cf.forward_documents(["d1", "d2", "d4"])
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_document_being_sent_by_another_worker_is_not_sent(enabled, fake_db, fake_bytes, posts):
    await fake_db.hub_documents.insert_one(_doc("d1", catalog_forward={"status": "sending"}))
    await cf.forward_documents(["d1"])
    assert posts == []


@pytest.mark.asyncio
async def test_large_download_is_skipped(monkeypatch, enabled, fake_db, posts):
    async def _big(doc):
        return b"x" * (cf.MAX_FILE_BYTES + 1)

    monkeypatch.setattr(cf, "load_document_bytes", _big)
    await fake_db.hub_documents.insert_one(_doc("d1", file_size=None))
    await cf.forward_documents(["d1"])
    assert posts == []
    doc = await fake_db.hub_documents.find_one({"id": "d1"})
    assert doc["catalog_forward"]["reason"] == "file_too_large"


@pytest.mark.asyncio
async def test_missing_url_or_key_is_recorded_not_sent(monkeypatch, enabled, fake_db, fake_bytes, posts):
    monkeypatch.delenv("CATALOG_FORWARD_KEY")
    await fake_db.hub_documents.insert_one(_doc("d1"))
    await cf.forward_documents(["d1"])
    assert posts == []
    doc = await fake_db.hub_documents.find_one({"id": "d1"})
    assert doc["catalog_forward"]["status"] == "failed"
    assert doc["catalog_forward"]["reason"].startswith("not_configured")


# ──────────────────────────────────────────────────────────────
# Failures never raise
# ──────────────────────────────────────────────────────────────

class _FailingClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **k):
        raise httpx.ConnectError("catalog inbox unreachable")


@pytest.mark.asyncio
async def test_failing_post_is_recorded_and_never_raises(monkeypatch, enabled, fake_db, fake_bytes):
    monkeypatch.setattr(cf.httpx, "AsyncClient", _FailingClient)
    await fake_db.hub_documents.insert_one(_doc("d1"))
    summary = await cf.forward_documents_safely(["d1"])
    assert summary is not None
    doc = await fake_db.hub_documents.find_one({"id": "d1"})
    assert doc["catalog_forward"]["status"] == "failed"
    assert doc["catalog_forward"]["reason"].startswith("submit_failed")
    assert not doc.get("catalog_forwarded_utc")


@pytest.mark.asyncio
async def test_http_error_status_is_a_failure(monkeypatch, enabled, fake_db, fake_bytes):
    def handler(request):
        assert request.headers["X-GPI-Intake-Key"] == KEY
        return httpx.Response(500, json={"detail": "boom"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        cf.httpx, "AsyncClient",
        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)),
    )
    await fake_db.hub_documents.insert_one(_doc("d1"))
    await cf.forward_documents(["d1"])
    doc = await fake_db.hub_documents.find_one({"id": "d1"})
    assert doc["catalog_forward"] == {**doc["catalog_forward"], "status": "failed", "reason": "submit_failed:catalog inbox returned HTTP 500"}


@pytest.mark.asyncio
async def test_unexpected_error_never_raises(monkeypatch, enabled):
    def _broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(cf, "get_db", _broken)
    assert await cf.forward_documents_safely(["d1"]) is None


@pytest.mark.asyncio
async def test_hook_runs_in_background_and_swallows_errors(monkeypatch, enabled):
    async def _explode(ids):
        raise RuntimeError("should be caught")

    monkeypatch.setattr(cf, "forward_documents", _explode)
    cf.schedule_forward_for_email(["d1"])  # must not raise
    await asyncio.sleep(0.01)
    assert not cf._background_tasks


def test_hook_without_event_loop_never_raises(enabled):
    cf.schedule_forward_for_email(["d1"])


def test_poller_hook_never_raises(monkeypatch):
    from services import email_polling_service as eps

    def _explode(ids):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf, "schedule_forward_for_email", _explode)
    eps._schedule_catalog_forward(["d1"])


# ──────────────────────────────────────────────────────────────
# Status and secrets
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_lists_decisions_without_key(enabled, fake_db, fake_bytes, posts):
    await fake_db.hub_documents.insert_many([
        _doc("d1"),
        _doc("d2", file_name="QUO-1001-Acme.pdf"),
    ])
    await cf.forward_documents(["d1", "d2"])
    status = await cf.get_status()
    assert status["settings"] == {"enabled": True, "dry_run": False, "url": URL, "key_configured": True}
    reasons = {(r["document_id"], r["status"], r["reason"]) for r in status["recent"]}
    assert ("d1", "sent", "accepted") in reasons
    assert ("d2", "skipped", "gamer_quote_to_customer") in reasons
    assert KEY not in repr(status)
    async for row in fake_db.hub_documents.find({}):
        assert KEY not in repr(row)
