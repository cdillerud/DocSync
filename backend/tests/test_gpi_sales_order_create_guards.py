"""Guards on POST /gpi-integration/sales-orders/from-document/{doc_id}.

Source exclusion, BC duplicate lookup (fail closed), and rollback of a header
whose lines didn't all post. BC and Mongo are faked; nothing leaves the process.
"""

import pytest
from fastapi import HTTPException

import routers.gpi_integration as gi


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = {d["id"]: d for d in (docs or [])}
        self.updates = []
        self.inserted = []

    async def find_one(self, query, projection=None):
        return self.docs.get(query.get("id"))

    async def update_one(self, query, update):
        self.updates.append((query, update))

    async def insert_one(self, doc):
        self.inserted.append(doc)


class FakeDB:
    def __init__(self, doc):
        self.hub_documents = FakeCollection([doc])
        self.bc_so_creation_audit = FakeCollection()


def customer_po(**overrides):
    doc = {
        "id": "doc-1",
        "document_type": "Sales_Order",
        "extracted_fields": {"po_number": "PO-45001", "order_date": "2026-09-01"},
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def bc(monkeypatch):
    """Patch every BC/DB touchpoint; returns a dict of call records to assert on."""
    calls = {"created": [], "lines": [], "deleted": [], "lookup": []}
    state = {"lines_added": None, "lookup": None, "lookup_error": None, "delete_ok": True}

    async def resolve_customer(doc):
        return {"customer_no": "C10000", "customer_name": "Example", "match_method": "test", "confidence": 1.0}

    async def resolve_lines(doc, customer_no=""):
        return [{"lineType": "Item", "lineObjectNumber": f"ITEM-{i}", "quantity": 1} for i in range(3)]

    async def find_existing(bc_service, *, customer_number="", external_document_number):
        calls["lookup"].append((customer_number, external_document_number))
        if state["lookup_error"]:
            raise RuntimeError(state["lookup_error"])
        return state["lookup"]

    async def create(**kwargs):
        calls["created"].append(kwargs)
        return {"success": True, "bc_record_no": "SO-1", "bc_system_id": "sys-1", "status": "created",
                "idempotency_key": kwargs["idempotency_key"]}

    async def add_lines(system_id, lines):
        calls["lines"].append(lines)
        added = len(lines) if state["lines_added"] is None else state["lines_added"]
        errors = [{"line": i + 1, "error": "bad item"} for i in range(added, len(lines))]
        return {"added": added, "total": len(lines), "errors": errors}

    async def delete(system_id):
        calls["deleted"].append(system_id)
        return {"deleted": state["delete_ok"], "status": 204 if state["delete_ok"] else 500, "error": ""}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(gi, "HAS_CREDENTIALS", True)
    monkeypatch.setattr(gi, "_resolve_customer_no", resolve_customer)
    monkeypatch.setattr(gi, "_resolve_sales_lines", resolve_lines)
    monkeypatch.setattr(gi, "_resolve_so_type", lambda doc: "standard")
    monkeypatch.setattr(gi, "find_existing_bc_sales_order", find_existing)
    monkeypatch.setattr(gi, "get_bc_service", lambda: object())
    monkeypatch.setattr(gi, "create_sales_order", create)
    monkeypatch.setattr(gi, "add_sales_order_lines", add_lines)
    monkeypatch.setattr(gi, "delete_sales_order", delete)
    monkeypatch.setattr(gi, "record_mapping_history", noop)
    return calls, state


def use_db(monkeypatch, doc):
    db = FakeDB(doc)
    monkeypatch.setattr(gi, "get_db", lambda: db)
    return db


def stamped(db):
    return [u for _, u in db.hub_documents.updates if "bc_sales_order" in u.get("$set", {})]


@pytest.mark.asyncio
async def test_gamer_vendor_po_is_refused_before_any_bc_call(monkeypatch, bc):
    calls, _ = bc
    use_db(monkeypatch, customer_po(email_subject="FW: Gamer Packaging Purchase Order Number: 111169"))

    with pytest.raises(HTTPException) as exc:
        await gi.create_sales_order_from_document("doc-1")

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "source_excluded"
    assert calls["lookup"] == [] and calls["created"] == []


@pytest.mark.asyncio
async def test_po_already_in_bc_is_refused(monkeypatch, bc):
    calls, state = bc
    state["lookup"] = {"number": "SO-900", "lookupEnvironment": "Production"}
    use_db(monkeypatch, customer_po())

    with pytest.raises(HTTPException) as exc:
        await gi.create_sales_order_from_document("doc-1")

    assert exc.value.status_code == 409
    assert exc.value.detail["bc_order_number"] == "SO-900"
    assert calls["lookup"] == [("C10000", "PO-45001")]
    assert calls["created"] == []


@pytest.mark.asyncio
async def test_duplicate_lookup_failure_fails_closed(monkeypatch, bc):
    calls, state = bc
    state["lookup_error"] = "HTTP 401"
    use_db(monkeypatch, customer_po())

    with pytest.raises(HTTPException) as exc:
        await gi.create_sales_order_from_document("doc-1")

    assert exc.value.status_code == 502
    assert exc.value.detail["error"] == "duplicate_lookup_failed"
    assert calls["created"] == []


@pytest.mark.asyncio
async def test_partial_lines_roll_back_the_header(monkeypatch, bc):
    calls, state = bc
    state["lines_added"] = 1
    db = use_db(monkeypatch, customer_po())

    with pytest.raises(HTTPException) as exc:
        await gi.create_sales_order_from_document("doc-1")

    assert exc.value.status_code == 502
    assert exc.value.detail["error"] == "lines_failed_rolled_back"
    assert calls["deleted"] == ["sys-1"]
    assert stamped(db) == []
    assert db.hub_documents.updates[-1][1]["$inc"] == {"bc_sales_order_rollback_count": 1}
    assert db.bc_so_creation_audit.inserted[-1]["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_retry_after_rollback_uses_a_fresh_idempotency_key(monkeypatch, bc):
    calls, _ = bc
    use_db(monkeypatch, customer_po(bc_sales_order_rollback_count=1))

    result = await gi.create_sales_order_from_document("doc-1")

    assert result["success"] is True
    assert calls["created"][0]["idempotency_key"] == gi._build_idempotency_key("doc-1", 1)
    assert calls["created"][0]["idempotency_key"] != gi._build_idempotency_key("doc-1")


@pytest.mark.asyncio
async def test_failed_rollback_records_the_partial_order_and_reports_failure(monkeypatch, bc):
    calls, state = bc
    state["lines_added"] = 2
    state["delete_ok"] = False
    db = use_db(monkeypatch, customer_po())

    result = await gi.create_sales_order_from_document("doc-1")

    assert result["success"] is False
    assert result["rollback_error"]
    assert "could not be deleted" in result["message"]
    # Stamped so a retry returns already_exists instead of creating a second order
    assert stamped(db)[0]["$set"]["bc_sales_order"]["bc_record_no"] == "SO-1"


@pytest.mark.asyncio
async def test_complete_order_is_created_and_stamped(monkeypatch, bc):
    calls, _ = bc
    db = use_db(monkeypatch, customer_po())

    result = await gi.create_sales_order_from_document("doc-1")

    assert result["success"] is True
    assert result["lines_added"] == 3
    assert calls["deleted"] == []
    assert stamped(db)[0]["$set"]["bc_sales_order"]["bc_record_no"] == "SO-1"


@pytest.mark.asyncio
async def test_order_from_intake_auto_create_is_not_duplicated(monkeypatch, bc):
    calls, _ = bc
    use_db(monkeypatch, customer_po(bc_sales_order_number="SO-5"))

    with pytest.raises(HTTPException) as exc:
        await gi.create_sales_order_from_document("doc-1")

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "auto_created"
    assert calls["created"] == []
