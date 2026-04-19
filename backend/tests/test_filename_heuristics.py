"""
Regression tests for v2.5.8 filename heuristics classifier.

Every rule must match at least one real-world filename from the user's
prod preview (iteration_227/229 samples). Also verifies the safety
properties: no BC mutations, idempotency, min_confidence gating, status
preservation.
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin.filename_heuristics_service import (
    classify_filename, preview, apply, recent_runs, list_rules,
    FILENAME_RULES,
)


@pytest.fixture
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_heur"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _unk(doc_id, file_name, vendor=None, **overrides):
    base = {
        "id": doc_id,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "file_name": file_name,
        "vendor_canonical": vendor,
        "reclaim_to_needs_review_at": _now(),
    }
    base.update(overrides)
    return base


# ────────── classify_filename: all rules match real prod data ──────────

@pytest.mark.parametrize("filename,vendor,expected_type,expected_rule", [
    # From prod sample iteration_227/229
    ("0305586_doc1.pdf", "TUMALOC",                   "AP_Invoice",        "tumaloc_numeric_freight"),
    ("0305181_doc1.pdf", "TUMALOC",                   "AP_Invoice",        "tumaloc_numeric_freight"),
    ("0303382.pdf",      "TUMALOC",                   "AP_Invoice",        "tumaloc_numeric_freight"),
    ("0305379_p1.pdf",   "TUMALOC",                   "AP_Invoice",        "tumaloc_numeric_freight"),
    ("Invoice-0493680_1_dragged__doc1_doc1_doc1.pdf", "CARGOMO",
                                                      "AP_Invoice",        "cargomo_invoice_prefix"),
    ("Valley Distributing Receiving Report (ZRECPOCNFMNLNG)_8335_20260408144621957.pdf",
                         "Valley Distributing",       "BOL",               "valley_receiving_report"),
    ("MARCH 2026 ACTIVITY.pdf",        "Brown Warehouse Company",
                                                      "Monthly_Statement", "brown_monthly_activity"),
    ("Scan2026-04-08_144056 WA2189-2190.pdf",  "SMC Worldwide LLC",
                                                      "BOL",               "smc_scan_warehouse_activity"),
    ("RENEWBIL_HEABRY_040310391622.pdf", "Progressive Logistics",
                                                      "BOL",               "progressive_renewbil"),
    ("Apex 112543 Outbound 4-8-26.pdf", "CROWN C",    "BOL",               "crown_apex_outbound"),
    ("W117508.pdf",      "GROUPWA",                   "BOL",               "groupwa_w_prefix"),
    ("W117505_p3.pdf",   "GROUPWA",                   "BOL",               "groupwa_w_prefix"),
    ("GAMMIN_AR_20260316.xls", "GAMMIN",              "AR_Statement",      "gammin_ar_statement"),
    ("112803.pdf",       "Lone Star Integrated Distribution, LLC",
                                                      "AP_Invoice",        "lonestar_numeric"),
    ("GamerPackaging_13790.pdf", "Valley Distributing and Storage Company",
                                                      "BOL",               "valley_gamerpackaging"),
])
def test_classify_matches_prod_filenames(filename, vendor, expected_type, expected_rule):
    result = classify_filename(filename, vendor)
    assert result is not None, f"No rule matched {filename!r} / vendor={vendor!r}"
    assert result["doc_type"] == expected_type
    assert result["rule_id"] == expected_rule
    assert 0.70 <= result["confidence"] <= 1.0


# ────────── Non-matches: must NOT reclassify these ──────────

@pytest.mark.parametrize("filename,vendor", [
    # Random non-matching filenames that should return None
    ("CI_PL_PO_111771_111779_16oz_Kimchi_Jar.pdf", None),
    ("Gamer Ship 3626.pdf", None),
    ("cmn_b3532cd1-5508-4db6-950a-b55451277b9c.png", "CARGOMO"),  # noise, handled elsewhere
    ("image.png", None),
    ("", None),
    ("some_random_file.pdf", "SOMEVENDOR"),
    # Numeric-only but from non-Lone Star vendor → no match
    ("112803.pdf", "UnknownVendor"),
    # Invoice-prefix but with too few digits
    ("Invoice-12.pdf", None),
])
def test_classify_no_false_positives(filename, vendor):
    assert classify_filename(filename, vendor) is None, (
        f"False positive: {filename!r} vendor={vendor!r}"
    )


def test_classify_handles_none_filename():
    assert classify_filename(None, "TUMALOC") is None
    assert classify_filename("", "TUMALOC") is None


# ────────── Rule-set sanity ──────────

def test_rules_all_have_evidence_notes():
    """Every rule MUST include a human-readable note — required for
    reviewer audit transparency."""
    for (rid, _vr, _fr, _dt, _conf, note) in FILENAME_RULES:
        assert note and isinstance(note, str) and len(note) > 10, (
            f"Rule {rid} is missing a meaningful note"
        )


def test_list_rules_endpoint_shape():
    rules = list_rules()
    assert len(rules) == len(FILENAME_RULES)
    for r in rules:
        assert {"rule_id", "filename_regex", "doc_type", "confidence", "note"} <= set(r)


# ────────── Preview ──────────

@pytest.mark.asyncio
async def test_preview_counts_matched_vs_unmatched(db):
    await db.hub_documents.insert_many([
        _unk("D1", "0303382.pdf", "TUMALOC"),
        _unk("D2", "W117508.pdf", "GROUPWA"),
        _unk("D3", "random_thing.pdf", "SomeVendor"),
        _unk("D4", "Invoice-0000001.pdf", "CARGOMO"),
    ])
    p = await preview(db=db)
    assert p["total_candidates"] == 4
    assert p["matched"] == 3
    assert p["unmatched"] == 1
    assert p["by_target_type"].get("AP_Invoice", 0) == 2
    assert p["by_target_type"].get("BOL", 0) == 1


@pytest.mark.asyncio
async def test_preview_does_not_mutate(db):
    await db.hub_documents.insert_many([_unk("P1", "0303382.pdf", "TUMALOC")])
    await preview(db=db)
    d = await db.hub_documents.find_one({"id": "P1"}, {"_id": 0})
    assert d["doc_type"] == "Unknown"
    assert d.get("filename_heuristic_applied_at") in (None, "", False)


# ────────── Apply: execute path ──────────

@pytest.mark.asyncio
async def test_apply_enriches_matched_docs(db):
    await db.hub_documents.insert_many([
        _unk("E1", "0303382.pdf", "TUMALOC"),
        _unk("E2", "W117508.pdf", "GROUPWA"),
        _unk("E3", "something_unrecognized.pdf"),
    ])
    r = await apply(db=db, execute=True, actor="meghan")
    assert r["applied_count"] == 2
    assert r["unmatched_count"] == 1

    e1 = await db.hub_documents.find_one({"id": "E1"}, {"_id": 0})
    assert e1["doc_type"] == "AP_Invoice"
    assert e1["document_type"] == "AP_Invoice"
    assert e1["suggested_job_type"] == "AP_Invoice"
    assert e1["doc_type_before_heuristic"] == "Unknown"
    assert e1["filename_heuristic_rule"] == "tumaloc_numeric_freight"
    assert e1["filename_heuristic_confidence"] == 0.85
    assert e1["filename_heuristic_applied"] is True
    assert "filename_heuristic_classified" in [
        h.get("event") for h in e1.get("workflow_history", [])
    ]
    # Never changes status — always requires human signoff
    assert e1["status"] == "NeedsReview"


@pytest.mark.asyncio
async def test_apply_respects_min_confidence(db):
    """A rule at 0.75 should NOT fire if min_confidence=0.80."""
    await db.hub_documents.insert_many([
        _unk("MC1", "112803.pdf", "Lone Star"),  # rule confidence 0.75
        _unk("MC2", "0303382.pdf", "TUMALOC"),   # rule confidence 0.85
    ])
    r = await apply(db=db, execute=True, min_confidence=0.80)
    assert r["applied_count"] == 1
    assert r["below_threshold_count"] == 1

    mc1 = await db.hub_documents.find_one({"id": "MC1"}, {"_id": 0})
    assert mc1["doc_type"] == "Unknown"  # unchanged
    mc2 = await db.hub_documents.find_one({"id": "MC2"}, {"_id": 0})
    assert mc2["doc_type"] == "AP_Invoice"


@pytest.mark.asyncio
async def test_apply_idempotent(db):
    await db.hub_documents.insert_many([_unk("I1", "0303382.pdf", "TUMALOC")])
    r1 = await apply(db=db, execute=True)
    assert r1["applied_count"] == 1
    r2 = await apply(db=db, execute=True)
    assert r2["applied_count"] == 0  # filter excludes already-applied


@pytest.mark.asyncio
async def test_apply_never_touches_bc_evidence(db):
    await db.hub_documents.insert_many([
        _unk("BC1", "0303382.pdf", "TUMALOC", bc_purchase_invoice_no="PI-X"),
        _unk("BC2", "0303382.pdf", "TUMALOC", bc_record_no="R-123"),
    ])
    r = await apply(db=db, execute=True)
    assert r["applied_count"] == 0
    bc1 = await db.hub_documents.find_one({"id": "BC1"}, {"_id": 0})
    assert bc1["doc_type"] == "Unknown"


@pytest.mark.asyncio
async def test_apply_audit_run_logged(db):
    await db.hub_documents.insert_many([_unk("A1", "0303382.pdf", "TUMALOC")])
    await apply(db=db, execute=True, actor="meghan")
    runs = await recent_runs(db=db)
    assert len(runs) == 1
    assert runs[0]["actor"] == "meghan"
    assert runs[0]["applied_count"] == 1


# ────────── Prod-shape scenario ──────────

@pytest.mark.asyncio
async def test_prod_shape_realistic_mix(db):
    """Mirror the user's actual 50-doc sample: mix of rule-hits and
    unrecognized names. Verify by_rule + by_target_type counts."""
    await db.hub_documents.insert_many([
        # 8 TUMALOC freight invoices
        *[_unk(f"T{i}", f"030{5000+i}_doc1.pdf", "TUMALOC") for i in range(8)],
        # 3 GROUPWA BOLs (incl. split pages)
        _unk("G1", "W117508.pdf", "GROUPWA"),
        _unk("G2", "W117505_p1.pdf", "GROUPWA"),
        _unk("G3", "W117505_p2.pdf", "GROUPWA"),
        # 1 CARGOMO invoice
        _unk("C1", "Invoice-0493680.pdf", "CARGOMO"),
        # 1 Valley receiving report
        _unk("V1", "Valley Distributing Receiving Report (ZRECPOCNFMNLNG)_8335.pdf",
             "Valley Distributing and Storage Company"),
        # 1 Brown monthly
        _unk("B1", "MARCH 2026 ACTIVITY.pdf", "Brown Warehouse Company"),
        # 4 genuinely unclassifiable
        _unk("U1", "CI_PL_PO_111771_111779_16oz_Kimchi_Jar.pdf"),
        _unk("U2", "Gamer Ship 3626.pdf"),
        _unk("U3", "misc_thing.pdf"),
        _unk("U4", "blurry_scan.pdf"),
    ])
    r = await apply(db=db, execute=True)
    assert r["applied_count"] == 14  # 8 + 3 + 1 + 1 + 1
    assert r["unmatched_count"] == 4
    assert r["by_target_type"]["AP_Invoice"] == 9   # 8 TUMALOC + 1 CARGOMO
    assert r["by_target_type"]["BOL"] == 4          # 3 GROUPWA + 1 Valley
    assert r["by_target_type"]["Monthly_Statement"] == 1
