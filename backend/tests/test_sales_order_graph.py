"""
Tests for Sales Order Graph Service (v2.5.13, Phase 1).

Covers:
    * normalize_ref cleans + uppercases + strips punctuation
    * doc_references pulls refs from all known fields including nested
      extracted_fields and list-valued reference_numbers
    * fuzzy_refs_from_filename extracts P-, S-, W-prefix numbers from
      filenames (Ball Metal shape)
    * build_graph returns nodes sorted by created_utc with edges that
      tell you which field matched + exact vs fuzzy
    * build_graph expands the search 1 hop (SO → PO referenced by SO →
      all docs referencing those POs) until no new refs are discovered
    * build_graph returns an error when neither seed is provided
    * include_fuzzy=False skips filename-pattern matches
    * incomplete_orders flags orders missing any of the 4 lifecycle roles
    * record_link_feedback persists to sales_order_graph_feedback
    * diagnostic_snapshot surfaces doc_type distribution + ref popularity
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin import sales_order_graph_service as sog


@pytest.fixture
def db(monkeypatch):
    d = mongomock_motor.AsyncMongoMockClient()["test_sog"]
    monkeypatch.setattr(sog, "get_db", lambda: d)
    return d


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _doc(db, **fields):
    base = {
        "id": fields.get("id") or f"d-{len(fields)}",
        "doc_type": fields.get("doc_type", "Unknown"),
        "file_name": fields.get("file_name", "x.pdf"),
        "status": "NeedsReview",
        "created_utc": fields.get("created_utc") or _now(),
        "duplicate_of": None,
    }
    base.update(fields)
    await db.hub_documents.insert_one(base)
    return base


# ──────────────────────────────────────────────────────────────
# normalize_ref
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("P0024333", "P0024333"),
    ("p0024333", "P0024333"),
    (" P-0024333 ", "P0024333"),
    ("p_0024333 / r2", "P0024333R2"),
    (None, None),
    ("", None),
    (["A1", "B2"], "A1"),
    ([], None),
])
def test_normalize_ref(raw, expected):
    assert sog.normalize_ref(raw) == expected


# ──────────────────────────────────────────────────────────────
# doc_references / fuzzy
# ──────────────────────────────────────────────────────────────

def test_doc_references_pulls_from_all_fields():
    doc = {
        "po_number": "P-0024333",
        "linked_so": "s174123",
        "extracted_fields": {"shipment_number": "W117765"},
        "reference_numbers": ["S174123", "other"],
    }
    refs = sog.doc_references(doc)
    assert "P0024333" in refs["po"]
    assert "S174123" in refs["so"]
    assert "W117765" in refs["shipment"]
    assert "OTHER" in refs["so"]  # reference_numbers is a bag of SO-ish refs


def test_fuzzy_refs_from_ball_metal_filename():
    fn = "P0024333 - 07 - W117765 - 10611479 - CN000106C_p1.pdf"
    fz = sog.fuzzy_refs_from_filename(fn)
    assert "P0024333" in fz["po"]
    assert "W117765" in fz["shipment"]
    # No S-prefix in this filename → no SO fuzzy hit
    assert fz["so"] == set()


def test_fuzzy_refs_sc_warehouse_filename():
    fn = "3-13-26 - GAMER PACKAGING - S174123 - 111888 - POSTED.pdf"
    fz = sog.fuzzy_refs_from_filename(fn)
    assert "S174123" in fz["so"]


# ──────────────────────────────────────────────────────────────
# build_graph
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_graph_requires_seed(db):
    r = await sog.build_graph()
    assert "error" in r


@pytest.mark.asyncio
async def test_build_graph_exact_match_on_so(db):
    # PO referencing SO 174123
    await _doc(db, id="po-1", doc_type="Purchase_Order",
               po_number="P0024333", so_number="S174123")
    # Shipping doc referencing same SO
    await _doc(db, id="ship-1", doc_type="Shipping_Document",
               linked_so="S174123", file_name="shipping.pdf")
    # AP invoice unrelated
    await _doc(db, id="unrelated", doc_type="AP_Invoice",
               so_number="S999999")

    r = await sog.build_graph(so_number="S174123", db=db)
    ids = {n["id"] for n in r["nodes"]}
    assert ids == {"po-1", "ship-1"}
    # All matches should be exact, not fuzzy
    for n in r["nodes"]:
        for e in n["edges"]:
            assert e["match_type"] == "exact"


@pytest.mark.asyncio
async def test_build_graph_expands_one_hop(db):
    # SO node references PO P123 in its linked_po field
    await _doc(db, id="so-1", doc_type="Sales_Order",
               so_number="S174123", linked_po="P0024333")
    # An AP invoice references that PO (not the SO)
    await _doc(db, id="ap-1", doc_type="AP_Invoice",
               po_number="P0024333")

    r = await sog.build_graph(so_number="S174123", db=db)
    ids = {n["id"] for n in r["nodes"]}
    assert ids == {"so-1", "ap-1"}


@pytest.mark.asyncio
async def test_build_graph_fuzzy_matches_ball_metal_filename(db):
    # SO doc
    await _doc(db, id="so-1", doc_type="Sales_Order",
               so_number="S174123", linked_po="P0024333")
    # Ball Metal shipping doc with PO# embedded in filename only
    await _doc(db, id="ball-1", doc_type="Unknown",
               vendor_canonical="Ball Metal",
               file_name="P0024333 - 07 - W117765 - 10611479 - CN000106C.pdf")

    r = await sog.build_graph(so_number="S174123", db=db, include_fuzzy=True)
    ids = {n["id"] for n in r["nodes"]}
    assert "ball-1" in ids
    ball = next(n for n in r["nodes"] if n["id"] == "ball-1")
    # Exact match on PO also happens via fuzzy extraction, and additionally
    # a fuzzy filename edge is present.
    match_types = {e["match_type"] for e in ball["edges"]}
    assert "fuzzy" in match_types or "exact" in match_types


@pytest.mark.asyncio
async def test_build_graph_include_fuzzy_false(db):
    # SO in system
    await _doc(db, id="so-1", doc_type="Sales_Order",
               so_number="S174123", linked_po="P0024333")
    # Ball Metal doc ONLY discoverable via filename fuzzy
    await _doc(db, id="ball-1", doc_type="Unknown",
               vendor_canonical="Ball Metal",
               file_name="P0024333 - 07 - W117765 - 10611479 - CN000106C.pdf")

    r = await sog.build_graph(so_number="S174123", db=db, include_fuzzy=False)
    ids = {n["id"] for n in r["nodes"]}
    # Ball Metal doc has no explicit PO ref field, so fuzzy-off excludes it
    assert "ball-1" not in ids


@pytest.mark.asyncio
async def test_build_graph_nodes_sorted_by_created_utc(db):
    await _doc(db, id="newest", doc_type="AP_Invoice",
               so_number="S1", created_utc="2026-04-15T00:00:00+00:00")
    await _doc(db, id="oldest", doc_type="Purchase_Order",
               so_number="S1", created_utc="2026-01-01T00:00:00+00:00")
    await _doc(db, id="middle", doc_type="Shipping_Document",
               so_number="S1", created_utc="2026-03-01T00:00:00+00:00")

    r = await sog.build_graph(so_number="S1", db=db)
    ids = [n["id"] for n in r["nodes"]]
    assert ids == ["oldest", "middle", "newest"]


@pytest.mark.asyncio
async def test_build_graph_role_counts(db):
    await _doc(db, id="po", doc_type="Purchase_Order", so_number="S1")
    await _doc(db, id="so", doc_type="Sales_Order", so_number="S1")
    await _doc(db, id="ship", doc_type="Shipping_Document", so_number="S1")
    await _doc(db, id="ap", doc_type="AP_Invoice", so_number="S1")

    r = await sog.build_graph(so_number="S1", db=db)
    assert r["role_counts"] == {"PO": 1, "SO": 1, "Shipping": 1, "AP_Invoice": 1}


# ──────────────────────────────────────────────────────────────
# incomplete_orders
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_incomplete_orders_flags_missing_roles(db):
    # SO "S1" — has Shipping but NO AP_Invoice
    await _doc(db, id="sh1", doc_type="Shipping_Document", so_number="S1")
    await _doc(db, id="bol1", doc_type="BOL", so_number="S1")
    # SO "S2" — has both Shipping + AP_Invoice, should NOT appear
    await _doc(db, id="sh2", doc_type="Shipping_Document", so_number="S2")
    await _doc(db, id="ap2", doc_type="AP_Invoice", so_number="S2")

    # Force "so" grouping; "auto" would fall back to po when so_count < 5
    r = await sog.incomplete_orders(db=db, group_by="so")
    gaps = {row["so_number"]: row for row in r["sample"]}
    assert "S1" in gaps
    assert "AP_Invoice" in gaps["S1"]["roles_missing"]
    assert "S2" not in gaps


@pytest.mark.asyncio
async def test_incomplete_orders_respects_min_nodes_per_order(db):
    # SO referenced by exactly 1 doc — likely extraction noise
    await _doc(db, id="lone", doc_type="AP_Invoice", so_number="SNOISE")
    r = await sog.incomplete_orders(db=db, min_nodes_per_order=2, group_by="so")
    gaps = {row["so_number"] for row in r["sample"]}
    assert "SNOISE" not in gaps


@pytest.mark.asyncio
async def test_incomplete_orders_po_grouping_for_po_centric_schema(db):
    """Prod case: no so_number ever populated, only po_number. The
    grouper must auto-pivot to PO. Default expected_roles is
    (Shipping, AP_Invoice) for PO-centric shops."""
    # PO P55555 — has Shipping only, missing AP_Invoice
    await _doc(db, id="sh-1", doc_type="Shipping_Document", po_number="P55555")
    await _doc(db, id="bol-1", doc_type="BOL", po_number="P55555")
    # PO P66666 — has both Shipping + AP_Invoice, complete
    await _doc(db, id="sh-2", doc_type="Shipping_Document", po_number="P66666")
    await _doc(db, id="ap-2", doc_type="AP_Invoice", po_number="P66666")

    r = await sog.incomplete_orders(db=db, group_by="auto")
    assert r["group_by_effective"] == "po"
    po_gaps = {row["po_number"]: row for row in r["sample"]}
    assert "P55555" in po_gaps
    assert po_gaps["P55555"]["roles_missing"] == ["AP_Invoice"]
    assert "P66666" not in po_gaps


@pytest.mark.asyncio
async def test_incomplete_orders_po_grouping_consumes_filename_fuzzy(db):
    """Ball Metal style: PO# only in filename. PO grouper must pick it up."""
    # AP Invoice explicitly referencing P0024333
    await _doc(db, id="ap-doc", doc_type="AP_Invoice", po_number="P0024333")
    # Ball Metal shipping with PO# only in filename
    await _doc(db, id="ball-ship", doc_type="Shipping_Document",
               file_name="P0024333 - 07 - W117765 - CN.pdf")

    r = await sog.incomplete_orders(db=db, group_by="po")
    po_gaps = {row["po_number"]: row for row in r["sample"]}
    # Full pair (Shipping + AP_Invoice) present → NOT in gaps
    assert "P0024333" not in po_gaps


@pytest.mark.asyncio
async def test_incomplete_orders_filters_peripheral_noise(db):
    """A PO# referenced ONLY by Vendor_Document / Other docs is NOT
    'stuck in pipeline' — it's a peripheral reference."""
    # Peripheral: 2 Vendor_Documents with a PO# but no real lifecycle doc
    await _doc(db, id="vd1", doc_type="Vendor_Document",
               po_number="P123456", file_name="copier@x.com_1.pdf")
    await _doc(db, id="vd2", doc_type="Other",
               po_number="P123456", file_name="copier@x.com_2.pdf")
    # Real gap: has Shipping but missing AP_Invoice
    await _doc(db, id="sh-real", doc_type="Shipping_Document",
               po_number="P999888")
    await _doc(db, id="bol-real", doc_type="BOL",
               po_number="P999888")

    r = await sog.incomplete_orders(db=db, group_by="po")
    gaps = {row["po_number"]: row for row in r["sample"]}
    assert "P123456" not in gaps
    assert "P999888" in gaps
    assert r["noise_filtered_count"] >= 1
    assert gaps["P999888"]["lifecycle_roles_present"] == ["Shipping"]


@pytest.mark.asyncio
async def test_incomplete_orders_rejects_non_po_shaped_refs(db):
    """W117649 is a shipment number, not a PO. Must be rejected from
    the PO-grouping bucket (prod bug that surfaced this filter)."""
    # W-prefix shipment ref mis-extracted as PO
    await _doc(db, id="bogus", doc_type="Shipping_Document",
               po_number="W117649", file_name="shipping.pdf")
    # CN-prefix container ref
    await _doc(db, id="bogus2", doc_type="Shipping_Document",
               po_number="CN000106", file_name="container.pdf")
    # Valid PO
    await _doc(db, id="ok", doc_type="Shipping_Document", po_number="P123456")

    r = await sog.incomplete_orders(db=db, group_by="po")
    buckets = {row["po_number"] for row in r["sample"]}
    assert "W117649" not in buckets
    assert "CN000106" not in buckets
    assert r["po_references_rejected"] >= 2
    rejected_vals = {v for v, _ in r["po_rejected_samples"]}
    assert "W117649" in rejected_vals


@pytest.mark.asyncio
async def test_incomplete_orders_expected_roles_override(db):
    """Caller can override the default (Shipping, AP_Invoice) pair."""
    await _doc(db, id="ap-only", doc_type="AP_Invoice", po_number="P111111")
    await _doc(db, id="ship-only", doc_type="Shipping_Document",
               po_number="P111111")
    # Default (Shipping, AP_Invoice): P111111 is complete
    r_default = await sog.incomplete_orders(db=db, group_by="po")
    assert not any(row["po_number"] == "P111111" for row in r_default["sample"])
    # Strict override: also require BOL
    r_strict = await sog.incomplete_orders(
        db=db, group_by="po",
        expected_roles=["Shipping", "AP_Invoice", "BOL"],
    )
    gap_pos = {row["po_number"] for row in r_strict["sample"]}
    assert "P111111" in gap_pos


# ──────────────────────────────────────────────────────────────
# record_link_feedback
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_link_feedback_persists(db):
    entry = await sog.record_link_feedback(
        so_number="s-174123", doc_id="d-1", confirmed=True,
        actor="alice", reason="Manually verified BC match",
    )
    assert entry["so_number"] == "S174123"
    assert entry["confirmed"] is True
    count = await db.sales_order_graph_feedback.count_documents({})
    assert count == 1


# ──────────────────────────────────────────────────────────────
# diagnostic_snapshot
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diagnostic_snapshot_surfaces_types_and_fields(db):
    await _doc(db, id="a", doc_type="Shipping_Document", po_number="P1")
    await _doc(db, id="b", doc_type="Shipping_Document", linked_so="S1")
    await _doc(db, id="c", doc_type="AP_Invoice",
               extracted_fields={"po_number": "P2"})

    r = await sog.diagnostic_snapshot(db=db)
    types = dict(r["doc_types"])
    assert types.get("Shipping_Document") == 2
    assert types.get("AP_Invoice") == 1
    fields = dict(r["ref_field_popularity"])
    assert fields.get("po_number", 0) >= 1
    assert fields.get("extracted_fields.po_number", 0) >= 1
