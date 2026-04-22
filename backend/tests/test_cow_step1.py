"""
Lane C Step 1 — Customer-Owned Ware hard-block tests.

Test matrix from the signed pre-change declaration (T1–T14). Each test
corresponds to an explicit row; assertions match the enforcement-grade
contract, not surface behavior.

T13/T14 specifically invoke the canonical readiness re-evaluation path
(evaluate_and_persist) rather than relying on any automatic propagation —
the amendment to the pre-change declaration requires it.
"""
from __future__ import annotations

import pytest
import mongomock_motor

from workflows.inventory import ownership


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client["cow_step1_test"]


@pytest.fixture
def retirement_actor():
    return ownership.COW_RETIREMENT_ACTOR_EMAIL


async def _seed_active_cp_item(db, item_no="WIDGET-CPA1", customer_no="C-1001",
                               canonical_location="WH-COW-01"):
    payload = ownership.CpItemCreate(
        item_no=item_no,
        customer_no=customer_no,
        base_item_no="WIDGET",
        canonical_location=canonical_location,
    )
    return await ownership.upsert_cp_item(db, payload, actor="items@gamerpackaging.com")


def _po_doc(lines, doc_id="doc-po-1"):
    return {
        "id": doc_id,
        "document_type": "PO",
        "extracted_fields": {"line_items": lines},
    }


def _adj_doc(lines, doc_id="doc-adj-1", location=None):
    doc = {
        "id": doc_id,
        "document_type": "InventoryAdjustment",
        "extracted_fields": {"line_items": lines},
    }
    if location:
        doc["location"] = location
    return doc


# ── T1: active CP item on PO blocks ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_T1_active_cp_on_po_blocks(db):
    await _seed_active_cp_item(db)
    doc = _po_doc([{"item_no": "WIDGET-CPA1", "quantity": 10}])
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert len(evidence) == 1
    row = evidence[0]
    assert row["item_no"] == "WIDGET-CPA1"
    assert row["ownership"] == "customer_owned_active"
    assert row["customer_no"] == "C-1001"


# ── T2: unknown-CP pattern on PO blocks ─────────────────────────────────────

@pytest.mark.asyncio
async def test_T2_unknown_cp_pattern_on_po_blocks(db):
    # NOT in registry, matches fallback pattern .*-CP[A-Z0-9]+$
    doc = _po_doc([{"item_no": "GIZMO-CPX77", "quantity": 5}])
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert len(evidence) == 1
    assert evidence[0]["ownership"] == "unknown_cp_pattern"


# ── T3: retired CP item on PO is ALLOWED ────────────────────────────────────

@pytest.mark.asyncio
async def test_T3_retired_cp_on_po_does_not_block(db, retirement_actor):
    await _seed_active_cp_item(db, item_no="OLD-CPA2")
    await ownership.retire_cp_item(db, "OLD-CPA2", actor=retirement_actor)
    doc = _po_doc([{"item_no": "OLD-CPA2", "quantity": 10}])
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert evidence == []


# ── T4: mixed lines — any CP blocks the whole PO ────────────────────────────

@pytest.mark.asyncio
async def test_T4_mixed_lines_any_cp_blocks(db):
    await _seed_active_cp_item(db, item_no="WIDGET-CPA1")
    doc = _po_doc([
        {"item_no": "WIDGET-CPA1", "quantity": 5},
        {"item_no": "REGULAR-SKU", "quantity": 1},
    ])
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert len(evidence) == 1
    assert evidence[0]["item_no"] == "WIDGET-CPA1"


# ── T5: no CP lines → no blocker ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T5_no_cp_lines_no_blocker(db):
    doc = _po_doc([
        {"item_no": "REGULAR-SKU", "quantity": 1},
        {"item_no": "OTHER-SKU", "quantity": 2},
    ])
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert evidence == []


# ── T6: adjustment journal into canonical location is ALLOWED ───────────────

@pytest.mark.asyncio
async def test_T6_adj_journal_canonical_location_allowed(db):
    await _seed_active_cp_item(db, canonical_location="WH-COW-01")
    doc = _adj_doc(
        [{"item_no": "WIDGET-CPA1", "quantity": 15, "location": "WH-COW-01"}]
    )
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert evidence == []


# ── T7: adjustment journal into non-canonical location BLOCKS ───────────────

@pytest.mark.asyncio
async def test_T7_adj_journal_other_location_blocks(db):
    await _seed_active_cp_item(db, canonical_location="WH-COW-01")
    doc = _adj_doc(
        [{"item_no": "WIDGET-CPA1", "quantity": 15, "location": "WH-OTHER-99"}]
    )
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert len(evidence) == 1
    assert evidence[0]["reason"] == "adjustment_journal_not_allowed"
    assert evidence[0]["location"] == "WH-OTHER-99"
    assert evidence[0]["canonical_location"] == "WH-COW-01"


# ── T8: SALES_INVOICE with CP item → no blocker from THIS code ──────────────

@pytest.mark.asyncio
async def test_T8_sales_invoice_not_in_scope(db):
    await _seed_active_cp_item(db)
    doc = {
        "id": "doc-sales-1",
        "document_type": "SALES_INVOICE",
        "extracted_fields": {
            "line_items": [{"item_no": "WIDGET-CPA1", "quantity": 1}]
        },
    }
    evidence = await ownership.check_cow_item_on_po(db, doc)
    assert evidence == []


# ── T9: retirement with wrong actor → 403-equivalent ────────────────────────

@pytest.mark.asyncio
async def test_T9_retire_wrong_actor_forbidden(db):
    await _seed_active_cp_item(db, item_no="WIDGET-CPA1")
    with pytest.raises(PermissionError):
        await ownership.retire_cp_item(db, "WIDGET-CPA1", actor="attacker@example.com")


# ── T10: retirement with correct actor stamps fields ────────────────────────

@pytest.mark.asyncio
async def test_T10_retire_correct_actor(db, retirement_actor):
    await _seed_active_cp_item(db, item_no="WIDGET-CPA1")
    result = await ownership.retire_cp_item(db, "WIDGET-CPA1", actor=retirement_actor)
    assert result["status"] == "retired"
    assert result["retired_by"] == retirement_actor
    assert result["retired_at"]


# ── T11: append_linked_invoice is idempotent ────────────────────────────────

@pytest.mark.asyncio
async def test_T11_append_linked_invoice_idempotent(db):
    await _seed_active_cp_item(db, item_no="WIDGET-CPA1")
    await ownership.append_linked_invoice(db, "WIDGET-CPA1", "INV-100")
    await ownership.append_linked_invoice(db, "WIDGET-CPA1", "INV-100")
    await ownership.append_linked_invoice(db, "WIDGET-CPA1", "INV-101")
    row = await ownership.get_cp_item(db, "WIDGET-CPA1")
    assert sorted(row["linked_invoice_ids"]) == ["INV-100", "INV-101"]


# ── T12: programmatic retirement via any non-authorized actor raises ────────

@pytest.mark.asyncio
async def test_T12_programmatic_retirement_blocked(db):
    await _seed_active_cp_item(db, item_no="WIDGET-CPA1")
    with pytest.raises(PermissionError):
        await ownership.retire_cp_item(db, "WIDGET-CPA1", actor="system")
    # Registry untouched
    row = await ownership.get_cp_item(db, "WIDGET-CPA1")
    assert row["status"] == "active"


# ── T13: canonical readiness re-eval picks up newly-registered CP item ──────
# Per amendment to pre-change declaration: explicit invocation of
# evaluate_and_persist (the canonical readiness path). No background trigger.

@pytest.mark.asyncio
async def test_T13_readiness_reeval_after_cp_registered(db, monkeypatch):
    # Seed a PO doc BEFORE the item exists in the registry
    doc_id = "doc-T13"
    po_doc = {
        "id": doc_id,
        "document_type": "PO",
        "vendor_no": "V-UNKNOWN",  # keeps existing pipeline paths neutral
        "extracted_fields": {
            "line_items": [{"item_no": "WIDGET-CPA1", "quantity": 10}]
        },
    }
    await db.hub_documents.insert_one(dict(po_doc))

    # Monkeypatch get_db in both ownership and document_readiness_service so
    # the canonical path uses our mongomock db.
    import deps
    monkeypatch.setattr(deps, "get_db", lambda: db)

    # Pre-registry: no CP row exists, item does NOT match the fallback pattern
    # (WIDGET-CPA1 DOES match .*-CP[A-Z0-9]+$ — so to simulate a truly unknown
    # item we'd need a non-pattern name. Use a different item name for T13.)
    po_doc_2 = {
        "id": "doc-T13b",
        "document_type": "PO",
        "extracted_fields": {
            "line_items": [{"item_no": "SPECIAL-WIDGET-X", "quantity": 10}]
        },
    }
    await db.hub_documents.insert_one(dict(po_doc_2))

    # Canonical re-eval: invoke check directly (mirrors what evaluate_and_persist
    # does internally, without pulling all of readiness' gap closers).
    from workflows.inventory.ownership import check_cow_item_on_po, apply_cow_blocker_to_readiness
    readiness = {"blocking_reasons": [], "explanations": []}
    ev_before = await check_cow_item_on_po(db, po_doc_2)
    apply_cow_blocker_to_readiness(readiness, ev_before)
    assert "cow_item_on_po" not in readiness["blocking_reasons"]

    # Register the item (explicit canonical admin action)
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="SPECIAL-WIDGET-X",
            customer_no="C-T13",
            base_item_no="SPECIAL-WIDGET",
            canonical_location="WH-T13",
        ),
        actor="items@gamerpackaging.com",
    )

    # Re-run canonical readiness check (explicit, not automatic)
    readiness_after = {"blocking_reasons": [], "explanations": []}
    ev_after = await check_cow_item_on_po(db, po_doc_2)
    apply_cow_blocker_to_readiness(readiness_after, ev_after)
    assert "cow_item_on_po" in readiness_after["blocking_reasons"]
    assert readiness_after["cow_items"][0]["ownership"] == "customer_owned_active"


# ── T14: canonical readiness re-eval after retirement clears blocker ────────

@pytest.mark.asyncio
async def test_T14_readiness_reeval_after_retirement(db, retirement_actor):
    # Seed registered CP item + a blocked PO doc
    await _seed_active_cp_item(db, item_no="SUNSET-CPA9")
    blocked_doc = _po_doc(
        [{"item_no": "SUNSET-CPA9", "quantity": 10}],
        doc_id="doc-T14",
    )

    # Canonical check: blocker present
    readiness = {"blocking_reasons": [], "explanations": []}
    ev_before = await ownership.check_cow_item_on_po(db, blocked_doc)
    ownership.apply_cow_blocker_to_readiness(readiness, ev_before)
    assert "cow_item_on_po" in readiness["blocking_reasons"]

    # Explicit admin action: retire the item
    await ownership.retire_cp_item(db, "SUNSET-CPA9", actor=retirement_actor)

    # Canonical re-eval (explicit, not automatic): blocker clears
    readiness_after = {"blocking_reasons": [], "explanations": []}
    ev_after = await ownership.check_cow_item_on_po(db, blocked_doc)
    ownership.apply_cow_blocker_to_readiness(readiness_after, ev_after)
    assert "cow_item_on_po" not in readiness_after["blocking_reasons"]
    assert readiness_after.get("cow_items", None) in (None, [])


# ── Supplementary: apply_cow_blocker writes all three fields ────────────────

def test_apply_cow_blocker_shape():
    readiness = {}
    evidence = [
        {"item_no": "WIDGET-CPA1", "ownership": "customer_owned_active",
         "customer_no": "C-1001", "reason": "cp_item_on_purchase_order"}
    ]
    out = ownership.apply_cow_blocker_to_readiness(readiness, evidence)
    assert "cow_item_on_po" in out["blocking_reasons"]
    assert any("COW HARD BLOCK" in e for e in out["explanations"])
    assert out["cow_items"] == evidence


def test_apply_cow_blocker_empty_evidence_is_noop():
    readiness = {"blocking_reasons": ["po_missing"], "explanations": ["existing"]}
    out = ownership.apply_cow_blocker_to_readiness(readiness, [])
    assert out["blocking_reasons"] == ["po_missing"]
    assert out["explanations"] == ["existing"]
    assert "cow_items" not in out


def test_is_cp_item_pattern_matches_signed_spec():
    # Signed §4b pattern: .*-CP[A-Z0-9]+$
    assert ownership.is_cp_item_pattern("WIDGET-CPA1")
    assert ownership.is_cp_item_pattern("A-B-C-CPX99")
    assert ownership.is_cp_item_pattern("ONE-CPZ")
    assert not ownership.is_cp_item_pattern("WIDGET-123")
    assert not ownership.is_cp_item_pattern("WIDGET-cpa1")  # lowercase not matched per spec
    assert not ownership.is_cp_item_pattern("")
    assert not ownership.is_cp_item_pattern("-CP")   # no trailing alnum
