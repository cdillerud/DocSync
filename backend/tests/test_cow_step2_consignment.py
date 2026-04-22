"""
Lane C Step 2 — Vendor Consignment enforcement tests.

Signed scope (2026-04-22):
  * Separate `consigned_item_registry` collection
  * Vendor-only consignor (no customer-consignor in this pass)
  * All 5 rules are hard blocks
  * Terminal `consumed` / `returned` — no reopen path
  * R3 widened: any sales doc referencing a consigned_in item blocks
"""
from __future__ import annotations

import pytest
import mongomock_motor

from workflows.inventory import ownership


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client["consignment_test"]


@pytest.fixture
def cons_actor():
    return ownership.CONSIGNMENT_STATE_ACTOR_EMAIL


async def _seed(db, item_no="COMP-A1", vendor_no="V-9001",
                physical_location="WH-CONS-01"):
    payload = ownership.ConsignedItemCreate(
        item_no=item_no,
        vendor_no=vendor_no,
        physical_location=physical_location,
    )
    return await ownership.upsert_consigned_item(
        db, payload, actor="admin@gamerpackaging.com"
    )


def _po(lines, doc_id="doc-po-c", document_type="PO"):
    return {"id": doc_id, "document_type": document_type,
            "extracted_fields": {"line_items": lines}}


def _ap_invoice(lines, doc_id="doc-ap-c"):
    return {"id": doc_id, "document_type": "AP_INVOICE",
            "extracted_fields": {"line_items": lines}}


def _sales(lines, doc_id="doc-so-c", customer_no="C-5001",
           document_type="SALES_INVOICE"):
    return {
        "id": doc_id, "document_type": document_type,
        "bc_customer_number": customer_no,
        "extracted_fields": {"line_items": lines},
    }


def _adj(lines, doc_id="doc-adj-c", location=None):
    doc = {"id": doc_id, "document_type": "InventoryAdjustment",
           "extracted_fields": {"line_items": lines}}
    if location:
        doc["location"] = location
    return doc


# ── K1–K8: registry + state machine ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_K1_upsert_creates_in_consigned_in(db):
    row = await _seed(db)
    assert row["state"] == "consigned_in"
    assert row["linked_consumption_ids"] == []
    assert row["linked_return_ids"] == []


@pytest.mark.asyncio
async def test_K2_upsert_never_flips_state(db, cons_actor):
    await _seed(db, item_no="COMP-A1")
    await ownership.transition_consigned_item(
        db, "COMP-A1", "consumed", actor=cons_actor, evidence_id="INV-1"
    )
    # A subsequent upsert on the same item_no must NOT reset state
    await ownership.upsert_consigned_item(
        db,
        ownership.ConsignedItemCreate(
            item_no="COMP-A1", vendor_no="V-9001", physical_location="WH-CONS-01",
            notes="later edit",
        ),
        actor="admin@gamerpackaging.com",
    )
    row = await ownership.get_consigned_item(db, "COMP-A1")
    assert row["state"] == "consumed"
    assert row["notes"] == "later edit"


@pytest.mark.asyncio
async def test_K3_consigned_in_to_consumed_stamps_audit(db, cons_actor):
    await _seed(db, item_no="COMP-A1")
    row = await ownership.transition_consigned_item(
        db, "COMP-A1", "consumed", actor=cons_actor, evidence_id="SI-100"
    )
    assert row["state"] == "consumed"
    assert row["state_changed_by"] == cons_actor
    assert row["state_changed_at"]
    assert "SI-100" in row["linked_consumption_ids"]
    assert row["linked_return_ids"] == []


@pytest.mark.asyncio
async def test_K4_consigned_in_to_returned_stamps_audit(db, cons_actor):
    await _seed(db, item_no="COMP-A2")
    row = await ownership.transition_consigned_item(
        db, "COMP-A2", "returned", actor=cons_actor, evidence_id="RET-10"
    )
    assert row["state"] == "returned"
    assert "RET-10" in row["linked_return_ids"]
    assert row["linked_consumption_ids"] == []


@pytest.mark.asyncio
async def test_K5_consumed_to_returned_rejected(db, cons_actor):
    await _seed(db, item_no="COMP-A3")
    await ownership.transition_consigned_item(
        db, "COMP-A3", "consumed", actor=cons_actor, evidence_id="SI-X"
    )
    with pytest.raises(ValueError, match="Illegal transition"):
        await ownership.transition_consigned_item(
            db, "COMP-A3", "returned", actor=cons_actor, evidence_id="RET-X"
        )


@pytest.mark.asyncio
async def test_K6_consumed_to_consigned_in_rejected(db, cons_actor):
    await _seed(db, item_no="COMP-A4")
    await ownership.transition_consigned_item(
        db, "COMP-A4", "consumed", actor=cons_actor, evidence_id="SI-Y"
    )
    # The only legal targets are consumed/returned, so this is rejected by
    # the target-state validator before the state-machine check.
    with pytest.raises(ValueError, match="Illegal target state"):
        await ownership.transition_consigned_item(
            db, "COMP-A4", "consigned_in", actor=cons_actor, evidence_id="RE-1"
        )


@pytest.mark.asyncio
async def test_K7_returned_to_consigned_in_rejected(db, cons_actor):
    """Per Q4 amendment: terminal states cannot be reopened."""
    await _seed(db, item_no="COMP-A5")
    await ownership.transition_consigned_item(
        db, "COMP-A5", "returned", actor=cons_actor, evidence_id="RET-Z"
    )
    with pytest.raises(ValueError, match="Illegal target state"):
        await ownership.transition_consigned_item(
            db, "COMP-A5", "consigned_in", actor=cons_actor, evidence_id="RE-2"
        )


@pytest.mark.asyncio
async def test_K8_actor_email_mismatch_blocks_transition(db):
    await _seed(db, item_no="COMP-A6")
    with pytest.raises(PermissionError):
        await ownership.transition_consigned_item(
            db, "COMP-A6", "consumed",
            actor="random@other.com", evidence_id="SI-Q",
        )
    # Registry untouched
    row = await ownership.get_consigned_item(db, "COMP-A6")
    assert row["state"] == "consigned_in"


@pytest.mark.asyncio
async def test_K8b_evidence_id_required(db, cons_actor):
    await _seed(db, item_no="COMP-A7")
    with pytest.raises(ValueError, match="evidence_id"):
        await ownership.transition_consigned_item(
            db, "COMP-A7", "consumed", actor=cons_actor, evidence_id="",
        )


# ── K9–K18: rule enforcement ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_K9_R1_ap_invoice_with_consigned_in_blocks(db):
    await _seed(db, item_no="COMP-A1")
    doc = _ap_invoice([{"item_no": "COMP-A1", "quantity": 10}])
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_AP
    assert ev[0]["state"] == "consigned_in"
    assert ev[0]["vendor_no"] == "V-9001"


@pytest.mark.asyncio
async def test_K9b_R1_po_with_consigned_in_also_blocks(db):
    await _seed(db, item_no="COMP-A1")
    doc = _po([{"item_no": "COMP-A1", "quantity": 10}])
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_AP


@pytest.mark.asyncio
async def test_K10_R1_regular_sku_no_trigger(db):
    doc = _ap_invoice([{"item_no": "REGULAR-SKU", "quantity": 1}])
    assert await ownership.check_consignment_rules(db, doc) == []


@pytest.mark.asyncio
async def test_K11_R2_ap_invoice_on_terminal_state_blocks(db, cons_actor):
    await _seed(db, item_no="COMP-A1")
    await ownership.transition_consigned_item(
        db, "COMP-A1", "consumed", actor=cons_actor, evidence_id="SI-99"
    )
    doc = _ap_invoice([{"item_no": "COMP-A1", "quantity": 5}])
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_AP_WRONG_STATE
    assert ev[0]["state"] == "consumed"


@pytest.mark.asyncio
async def test_K12_R2_non_trigger_when_item_not_in_registry(db):
    doc = _ap_invoice([{"item_no": "NEVER-CONSIGNED", "quantity": 1}])
    assert await ownership.check_consignment_rules(db, doc) == []


@pytest.mark.asyncio
async def test_K13_R3_widened_any_sales_doc_with_consigned_in_blocks(db):
    """Widened rule (signed): customer identity is irrelevant."""
    await _seed(db, item_no="COMP-A1")
    for customer_no in ("C-5001", "V-9001", "SOME-OTHER-CUST"):
        doc = _sales(
            [{"item_no": "COMP-A1", "quantity": 1}],
            customer_no=customer_no,
        )
        ev = await ownership.check_consignment_rules(db, doc)
        assert len(ev) == 1, f"customer_no={customer_no} should block"
        assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO
        assert ev[0]["state"] == "consigned_in"


@pytest.mark.asyncio
async def test_K14_R3_no_trigger_if_item_not_consigned(db):
    doc = _sales([{"item_no": "REGULAR-SKU", "quantity": 1}])
    assert await ownership.check_consignment_rules(db, doc) == []


@pytest.mark.asyncio
async def test_K15_R4_post_lifecycle_on_sales_blocks(db, cons_actor):
    await _seed(db, item_no="COMP-A1")
    await ownership.transition_consigned_item(
        db, "COMP-A1", "consumed", actor=cons_actor, evidence_id="SI-START"
    )
    doc = _sales([{"item_no": "COMP-A1", "quantity": 2}])
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO_POST
    assert ev[0]["state"] == "consumed"


@pytest.mark.asyncio
async def test_K15b_R4_post_lifecycle_returned_also_blocks(db, cons_actor):
    await _seed(db, item_no="COMP-A2")
    await ownership.transition_consigned_item(
        db, "COMP-A2", "returned", actor=cons_actor, evidence_id="RET-1"
    )
    doc = _sales([{"item_no": "COMP-A2", "quantity": 1}])
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO_POST


@pytest.mark.asyncio
async def test_K16_R4_not_warn_level(db, cons_actor):
    """Per Q3 amendment: R4 is a block, not a warn. Evidence must route to
    blocking_reasons (not warning_reasons) via the helper."""
    await _seed(db, item_no="COMP-A1")
    await ownership.transition_consigned_item(
        db, "COMP-A1", "consumed", actor=cons_actor, evidence_id="SI-1"
    )
    doc = _sales([{"item_no": "COMP-A1", "quantity": 1}])
    evidence = await ownership.check_consignment_rules(db, doc)

    readiness = {"blocking_reasons": [], "warning_reasons": [], "explanations": []}
    ownership.apply_consignment_blocker_to_readiness(readiness, evidence)
    assert "consigned_item_post_lifecycle_on_so" in readiness["blocking_reasons"]
    assert "consigned_item_post_lifecycle_on_so" not in readiness["warning_reasons"]


@pytest.mark.asyncio
async def test_K17_R5_adj_journal_wrong_location_blocks(db):
    await _seed(db, item_no="COMP-A1", physical_location="WH-CONS-01")
    doc = _adj(
        [{"item_no": "COMP-A1", "quantity": 5, "location": "WH-OTHER"}]
    )
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_ADJ_LOC
    assert ev[0]["location"] == "WH-OTHER"
    assert ev[0]["physical_location"] == "WH-CONS-01"


@pytest.mark.asyncio
async def test_K18_R5_adj_journal_matching_location_no_trigger(db):
    await _seed(db, item_no="COMP-A1", physical_location="WH-CONS-01")
    doc = _adj(
        [{"item_no": "COMP-A1", "quantity": 5, "location": "WH-CONS-01"}]
    )
    assert await ownership.check_consignment_rules(db, doc) == []


# ── K19–K20: canonical re-eval flip (explicit, per amendment) ──────────────

@pytest.mark.asyncio
async def test_K19_reeval_adds_blocker_after_registration(db):
    doc = _sales([{"item_no": "COMP-NEW", "quantity": 2}])
    # Pre-registration: no evidence
    assert await ownership.check_consignment_rules(db, doc) == []
    # Register → explicit re-eval surfaces the blocker
    await _seed(db, item_no="COMP-NEW")
    ev = await ownership.check_consignment_rules(db, doc)
    assert len(ev) == 1
    assert ev[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO


@pytest.mark.asyncio
async def test_K20_reeval_flips_evidence_across_state_transition(db, cons_actor):
    await _seed(db, item_no="COMP-FLIP")
    sales_doc = _sales([{"item_no": "COMP-FLIP", "quantity": 1}])
    ap_doc = _ap_invoice([{"item_no": "COMP-FLIP", "quantity": 1}])

    # consigned_in: SO blocks with _on_sales_doc, AP blocks with _on_ap_invoice
    so_ev1 = await ownership.check_consignment_rules(db, sales_doc)
    ap_ev1 = await ownership.check_consignment_rules(db, ap_doc)
    assert so_ev1[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO
    assert ap_ev1[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_AP

    # Transition to consumed
    await ownership.transition_consigned_item(
        db, "COMP-FLIP", "consumed", actor=cons_actor, evidence_id="SI-F1"
    )

    # Now SO blocks with _post_lifecycle_on_so, AP blocks with _wrong_state_on_ap
    so_ev2 = await ownership.check_consignment_rules(db, sales_doc)
    ap_ev2 = await ownership.check_consignment_rules(db, ap_doc)
    assert so_ev2[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_SO_POST
    assert ap_ev2[0]["blocker_code"] == ownership.BLOCKER_CODE_CONS_AP_WRONG_STATE


# ── K21–K22: cross-gate isolation from COW ──────────────────────────────────

@pytest.mark.asyncio
async def test_K21_consignment_check_does_not_fire_on_cp_items(db):
    """A CP item (in cp_item_registry) must not trigger consignment rules."""
    # Seed CP registry only
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="WIDGET-CPA1", customer_no="C-1001",
            base_item_no="WIDGET", canonical_location="WH-COW-01",
        ),
        actor="items@gamerpackaging.com",
    )
    doc = _sales([{"item_no": "WIDGET-CPA1", "quantity": 1}])
    assert await ownership.check_consignment_rules(db, doc) == []


@pytest.mark.asyncio
async def test_K22_cp_checks_do_not_fire_on_consigned_items(db):
    """A consignment item (in consigned_item_registry only) must not trigger
    COW rules unless it also happens to match the CP fallback pattern."""
    await _seed(db, item_no="COMP-X1")   # not a -CP<alphanum> pattern
    doc = _sales([{"item_no": "COMP-X1", "quantity": 1}])
    cow_ev = await ownership.check_cow_so_uses_base_item(db, doc)
    assert cow_ev == []
    cons_ev = await ownership.check_consignment_rules(db, doc)
    assert len(cons_ev) == 1


# ── apply_cow/consignment_blocker helper semantics ──────────────────────────

def test_apply_consignment_writes_to_consigned_items_field():
    readiness = {}
    evidence = [{
        "blocker_code": ownership.BLOCKER_CODE_CONS_SO,
        "item_no": "COMP-A1",
        "state": "consigned_in",
        "vendor_no": "V-9001",
        "reason": "consigned_in_item_on_sales_doc",
    }]
    out = ownership.apply_consignment_blocker_to_readiness(readiness, evidence)
    assert "consigned_items" in out
    assert "cow_items" not in out
    assert "cow_so_items" not in out
    assert "consigned_item_on_sales_doc" in out["blocking_reasons"]


def test_apply_consignment_multiple_codes_get_distinct_explanations():
    readiness = {}
    evidence = [
        {"blocker_code": ownership.BLOCKER_CODE_CONS_AP, "item_no": "A-1",
         "state": "consigned_in", "vendor_no": "V-1", "reason": ""},
        {"blocker_code": ownership.BLOCKER_CODE_CONS_ADJ_LOC, "item_no": "A-2",
         "state": "consigned_in", "vendor_no": "V-1",
         "location": "X", "physical_location": "Y", "reason": ""},
    ]
    out = ownership.apply_consignment_blocker_to_readiness(readiness, evidence)
    assert set(out["blocking_reasons"]) == {
        "consigned_item_on_ap_invoice",
        "consigned_item_wrong_location_on_adj",
    }
    assert len(out["explanations"]) == 2
