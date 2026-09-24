"""Intake auto-create of BC sales orders gets the rep path's guards.

Source exclusion, no-lines refusal, BC duplicate lookup (fail closed),
rollback of a header whose lines didn't all post, and a cross-check with
orders created from the review page. BC and Mongo are faked.
"""

import pytest

import services.auto_post_service as aps
import services.bc_post_claim as claim_mod
import services.sales_order_bc_lookup as lookup_mod


class Coll:
    def __init__(self):
        self.updates = []

    async def update_one(self, query, update):
        self.updates.append(update)


class DB:
    def __init__(self):
        self.hub_documents = Coll()


class FakeBC:
    use_mock = False

    def __init__(self, lines_added=None, delete_ok=True):
        self.lines_added = lines_added
        self.delete_ok = delete_ok
        self.created = []
        self.deleted = []

    async def create_sales_order(self, order_data):
        self.created.append(order_data)
        total = len(order_data["lines"])
        added = total if self.lines_added is None else self.lines_added
        return {"success": True, "bcDocumentId": "so-sys-1", "bcDocumentNumber": "SO-1",
                "linesAdded": added, "linesTotal": total, "lineErrors": ["bad item"] * (total - added)}

    async def delete_sales_order(self, order_id):
        self.deleted.append(order_id)
        return {"deleted": self.delete_ok, "status": 204 if self.delete_ok else 500, "error": ""}


def po(**overrides):
    doc = {"id": "doc-1", "doc_type": "SALES_ORDER", "customer_extracted": "Example Co",
           "order_number_extracted": "PO-45001", "line_items": [{"description": "a"}, {"description": "b"}]}
    doc.update(overrides)
    return doc


@pytest.fixture
def env(monkeypatch):
    state = {"lookup": None, "lookup_error": None, "released": []}

    async def lookup_customer(name, bc):
        return "C10000", "SP1"

    async def find_existing(bc_service, *, customer_number="", external_document_number):
        if state["lookup_error"]:
            raise RuntimeError(state["lookup_error"])
        return state["lookup"]

    async def claim(db, **kwargs):
        return claim_mod.ClaimResult(claimed=True)

    async def release(db, doc_id, final_state, extra_set=None, attempt=None):
        state["released"].append((final_state, extra_set or {}))

    monkeypatch.setattr(aps, "check_sales_order_eligibility", lambda doc: (True, ""))
    monkeypatch.setattr(aps, "_lookup_bc_customer", lookup_customer)
    monkeypatch.setattr(lookup_mod, "find_existing_bc_sales_order", find_existing)
    monkeypatch.setattr(claim_mod, "claim_for_bc_post", claim)
    monkeypatch.setattr(claim_mod, "release_claim", release)
    return state


async def run(doc, bc):
    db = DB()
    return await aps.attempt_auto_create_sales_order(doc["id"], doc, db, bc), db


@pytest.mark.asyncio
async def test_gamer_vendor_po_is_not_created(env):
    bc = FakeBC()
    result, db = await run(po(email_subject="FW: Gamer Packaging Purchase Order Number: 111169"), bc)

    assert result.success is False and result.reason == "Source excluded"
    assert bc.created == []
    assert db.hub_documents.updates[-1]["$set"]["review_status"] == "needs_review"


@pytest.mark.asyncio
async def test_no_lines_is_not_created(env):
    bc = FakeBC()
    result, _ = await run(po(line_items=[]), bc)

    assert result.reason == "No lines" and bc.created == []


@pytest.mark.asyncio
async def test_po_already_in_bc_is_not_created(env):
    env["lookup"] = {"number": "SO-900"}
    bc = FakeBC()
    result, _ = await run(po(), bc)

    assert result.reason == "Already in BC" and "SO-900" in result.error
    assert bc.created == []


@pytest.mark.asyncio
async def test_duplicate_lookup_failure_fails_closed(env):
    env["lookup_error"] = "HTTP 401"
    bc = FakeBC()
    result, _ = await run(po(), bc)

    assert result.reason == "Duplicate lookup failed" and bc.created == []


@pytest.mark.asyncio
async def test_order_from_review_page_is_not_duplicated(env):
    bc = FakeBC()
    result, _ = await run(po(bc_sales_order={"bc_record_no": "SO-7"}), bc)

    assert result.eligible is False and bc.created == []


@pytest.mark.asyncio
async def test_partial_lines_roll_back(env):
    bc = FakeBC(lines_added=1)
    result, _ = await run(po(), bc)

    assert result.success is False and result.reason == "Lines failed; order rolled back"
    assert bc.deleted == ["so-sys-1"]
    final_state, extra = env["released"][-1]
    assert final_state == "auto_create_failed"
    assert "bc_sales_order_number" not in extra


@pytest.mark.asyncio
async def test_failed_rollback_records_order_as_created(env):
    bc = FakeBC(lines_added=1, delete_ok=False)
    result, _ = await run(po(), bc)

    assert result.success is False and result.reason == "Lines failed; rollback failed"
    final_state, extra = env["released"][-1]
    assert final_state == "created"  # terminal: blocks a second order
    assert extra["bc_sales_order_number"] == "SO-1"
    assert extra["review_status"] == "needs_review"


@pytest.mark.asyncio
async def test_complete_order_is_created(env):
    bc = FakeBC()
    result, _ = await run(po(), bc)

    assert result.success is True and bc.deleted == []
    assert env["released"][-1][0] == "created"
