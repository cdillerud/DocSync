"""
Bake-Off Router
Internal benchmarking workspace for GPI Hub vs Square 9 comparison.
All endpoints under /bakeoff/.
"""

import logging
import io
import csv
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intake-benchmark", tags=["Intake Benchmark"])

RUNS_COLL = "bakeoff_runs"
DOCS_COLL = "bakeoff_documents"

WHY_WRONG_TAGS = [
    "Vendor alias miss", "Vendor resolution error", "PO not found",
    "PO mismatch", "Classification error", "OCR issue",
    "Wrong folder / route", "Incomplete extraction",
    "Duplicate handling issue", "Ambiguous document",
    "Human process issue", "Other",
]

# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════

class CreateRunReq(BaseModel):
    name: str
    description: str = ""
    test_date: str = ""
    source_batch_identifier: str = ""
    expected_document_count: int = 0

class UpdateRunReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    test_date: Optional[str] = None
    source_batch_identifier: Optional[str] = None
    expected_document_count: Optional[int] = None

class AddDocumentReq(BaseModel):
    document_id: str = ""
    file_name: str = ""
    source_path: str = ""
    received_date: str = ""
    vendor_truth: str = ""
    doc_type_truth: str = ""
    amount_truth: Optional[float] = None
    po_truth: str = ""
    folder_truth: str = ""
    truth_notes: str = ""

class UpdateDocScoringReq(BaseModel):
    # Truth fields
    vendor_truth: Optional[str] = None
    doc_type_truth: Optional[str] = None
    amount_truth: Optional[float] = None
    po_truth: Optional[str] = None
    folder_truth: Optional[str] = None
    truth_notes: Optional[str] = None
    # GPI fields (manual override)
    gpi_ingested: Optional[bool] = None
    gpi_doc_type: Optional[str] = None
    gpi_vendor: Optional[str] = None
    gpi_amount: Optional[float] = None
    gpi_po: Optional[str] = None
    gpi_folder_output: Optional[str] = None
    gpi_needs_review: Optional[str] = None
    gpi_final_status: Optional[str] = None
    gpi_notes: Optional[str] = None
    # GPI correctness overrides
    gpi_doc_type_correct: Optional[bool] = None
    gpi_vendor_correct: Optional[bool] = None
    gpi_amount_correct: Optional[bool] = None
    gpi_po_correct: Optional[bool] = None
    gpi_folder_correct: Optional[bool] = None
    gpi_why_wrong_tags: Optional[List[str]] = None
    # S9 fields
    s9_ingested: Optional[bool] = None
    s9_doc_type: Optional[str] = None
    s9_vendor: Optional[str] = None
    s9_amount: Optional[float] = None
    s9_po: Optional[str] = None
    s9_folder_output: Optional[str] = None
    s9_needs_review: Optional[str] = None
    s9_final_status: Optional[str] = None
    s9_notes: Optional[str] = None
    # S9 correctness overrides
    s9_doc_type_correct: Optional[bool] = None
    s9_vendor_correct: Optional[bool] = None
    s9_amount_correct: Optional[bool] = None
    s9_po_correct: Optional[bool] = None
    s9_folder_correct: Optional[bool] = None
    s9_why_wrong_tags: Optional[List[str]] = None


# ═══════════════════════════════════════════════════════════════
# NORMALIZATION HELPERS
# ═══════════════════════════════════════════════════════════════

def _norm_str(s):
    """Normalize string for comparison: lowercase, strip."""
    if s is None:
        return ""
    return str(s).strip().lower()

def _norm_po(po):
    """Normalize PO number: remove common prefixes, strip whitespace/case."""
    if not po:
        return ""
    s = str(po).strip().upper()
    # Remove common PO prefixes including optional hyphen/space after
    s = re.sub(r'^(PO|P\.O\.?|PO#|P\.O\.#|#)[-\s]*', '', s, flags=re.IGNORECASE)
    s = s.strip().lstrip('0')
    return s.lower()

def _amounts_match(a, b, tolerance=0.01):
    """Compare two amounts with tolerance."""
    if a is None or b is None:
        return None
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (ValueError, TypeError):
        return None

def auto_score_correctness(doc):
    """Auto-calculate correctness flags by comparing values to truth."""
    updates = {}
    # String comparisons
    for prefix in ("gpi", "s9"):
        for field in ("doc_type", "vendor", "folder"):
            truth_val = _norm_str(doc.get(f"{field}_truth"))
            sys_val = _norm_str(doc.get(f"{prefix}_{field}") if field != "folder" else doc.get(f"{prefix}_folder_output"))
            key = f"{prefix}_{field}_correct"
            # Only auto-score if truth is set and not manually overridden
            if truth_val and sys_val:
                updates[key] = truth_val == sys_val
            elif truth_val and not sys_val:
                updates[key] = False

        # PO comparison with normalization
        truth_po = _norm_po(doc.get("po_truth"))
        sys_po = _norm_po(doc.get(f"{prefix}_po"))
        if truth_po and sys_po:
            updates[f"{prefix}_po_correct"] = truth_po == sys_po
        elif truth_po and not sys_po:
            updates[f"{prefix}_po_correct"] = False

        # Amount comparison
        truth_amt = doc.get("amount_truth")
        sys_amt = doc.get(f"{prefix}_amount")
        result = _amounts_match(truth_amt, sys_amt)
        if result is not None:
            updates[f"{prefix}_amount_correct"] = result

    return updates


# ═══════════════════════════════════════════════════════════════
# RUN ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("/runs")
async def create_run(req: CreateRunReq):
    db = get_db()
    run_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": run_id,
        "name": req.name,
        "description": req.description,
        "test_date": req.test_date,
        "source_batch_identifier": req.source_batch_identifier,
        "status": "draft",
        "expected_document_count": req.expected_document_count,
        "actual_document_count": 0,
        "created_by": "admin",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "archived_at": None,
    }
    await db[RUNS_COLL].insert_one(run)
    run.pop("_id", None)
    return run


@router.get("/runs")
async def list_runs(status: Optional[str] = None):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    runs = await db[RUNS_COLL].find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"runs": runs, "total": len(runs)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    db = get_db()
    run = await db[RUNS_COLL].find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    doc_count = await db[DOCS_COLL].count_documents({"run_id": run_id})
    run["actual_document_count"] = doc_count
    return run


@router.put("/runs/{run_id}")
async def update_run(run_id: str, req: UpdateRunReq):
    db = get_db()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db[RUNS_COLL].update_one({"run_id": run_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Run not found")
    return await get_run(run_id)


@router.post("/runs/{run_id}/complete")
async def complete_run(run_id: str):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = await db[RUNS_COLL].update_one(
        {"run_id": run_id},
        {"$set": {"status": "complete", "completed_at": now, "updated_at": now}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Run not found")
    return {"status": "complete"}


@router.post("/runs/{run_id}/archive")
async def archive_run(run_id: str):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = await db[RUNS_COLL].update_one(
        {"run_id": run_id},
        {"$set": {"status": "archived", "archived_at": now, "updated_at": now}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Run not found")
    return {"status": "archived"}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    db = get_db()
    run = await db[RUNS_COLL].find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")
    if run["status"] != "draft":
        raise HTTPException(400, "Only draft runs can be deleted")
    await db[DOCS_COLL].delete_many({"run_id": run_id})
    await db[RUNS_COLL].delete_one({"run_id": run_id})
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════
# DOCUMENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════

def _make_doc(run_id: str, data: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    doc_id = data.get("document_id") or str(uuid.uuid4())[:12]
    return {
        "run_id": run_id,
        "doc_uid": str(uuid.uuid4())[:12],
        "document_id": doc_id,
        "file_name": data.get("file_name", ""),
        "source_path": data.get("source_path", ""),
        "received_date": data.get("received_date", ""),
        # Truth
        "vendor_truth": data.get("vendor_truth", ""),
        "doc_type_truth": data.get("doc_type_truth", ""),
        "amount_truth": data.get("amount_truth"),
        "po_truth": data.get("po_truth", ""),
        "folder_truth": data.get("folder_truth", ""),
        "truth_notes": data.get("truth_notes", ""),
        # GPI raw
        "gpi_ingested": None,
        "gpi_doc_type": None, "gpi_vendor": None,
        "gpi_amount": None, "gpi_po": None,
        "gpi_folder_output": None,
        "gpi_needs_review": None, "gpi_final_status": None,
        "gpi_notes": "", "gpi_auto_linked": False, "gpi_manually_edited": False,
        "gpi_source_document_id": None,
        # GPI correctness
        "gpi_doc_type_correct": None, "gpi_vendor_correct": None,
        "gpi_amount_correct": None, "gpi_po_correct": None,
        "gpi_folder_correct": None, "gpi_why_wrong_tags": [],
        # S9 raw
        "s9_ingested": None,
        "s9_doc_type": None, "s9_vendor": None,
        "s9_amount": None, "s9_po": None,
        "s9_folder_output": None,
        "s9_needs_review": None, "s9_final_status": None, "s9_notes": "",
        # S9 correctness
        "s9_doc_type_correct": None, "s9_vendor_correct": None,
        "s9_amount_correct": None, "s9_po_correct": None,
        "s9_folder_correct": None, "s9_why_wrong_tags": [],
        # Audit
        "created_at": now, "updated_at": now,
    }


@router.post("/runs/{run_id}/documents")
async def add_document(run_id: str, req: AddDocumentReq):
    db = get_db()
    run = await db[RUNS_COLL].find_one({"run_id": run_id})
    if not run:
        raise HTTPException(404, "Run not found")
    doc = _make_doc(run_id, req.dict())
    await db[DOCS_COLL].insert_one(doc)
    doc.pop("_id", None)
    await db[RUNS_COLL].update_one({"run_id": run_id}, {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}})
    return doc


@router.post("/runs/{run_id}/documents/import")
async def bulk_import_documents(run_id: str, file: UploadFile = File(...)):
    """Import documents from CSV. Columns: document_id, file_name, source_path, received_date, vendor_truth, doc_type_truth, amount_truth, po_truth, folder_truth"""
    db = get_db()
    run = await db[RUNS_COLL].find_one({"run_id": run_id})
    if not run:
        raise HTTPException(404, "Run not found")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    docs = []
    for row in reader:
        # Parse amount
        amt = row.get("amount_truth", "")
        try:
            amt = float(amt) if amt else None
        except ValueError:
            amt = None
        row["amount_truth"] = amt
        docs.append(_make_doc(run_id, row))

    if docs:
        await db[DOCS_COLL].insert_many(docs)
        for d in docs:
            d.pop("_id", None)

    await db[RUNS_COLL].update_one({"run_id": run_id}, {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}})
    return {"imported": len(docs)}


@router.get("/runs/{run_id}/documents")
async def list_documents(
    run_id: str,
    final_status: Optional[str] = None,
    needs_review: Optional[str] = None,
    why_wrong: Optional[str] = None,
    doc_type: Optional[str] = None,
    vendor: Optional[str] = None,
    has_gpi_link: Optional[bool] = None,
    has_s9_data: Optional[bool] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
):
    db = get_db()
    query = {"run_id": run_id}

    if final_status:
        query["$or"] = [
            {"gpi_final_status": final_status},
            {"s9_final_status": final_status},
        ]
    if needs_review:
        query["$or"] = [
            {"gpi_needs_review": needs_review},
            {"s9_needs_review": needs_review},
        ]
    if why_wrong:
        query["$or"] = [
            {"gpi_why_wrong_tags": why_wrong},
            {"s9_why_wrong_tags": why_wrong},
        ]
    if doc_type:
        query["doc_type_truth"] = {"$regex": doc_type, "$options": "i"}
    if vendor:
        query["vendor_truth"] = {"$regex": vendor, "$options": "i"}
    if has_gpi_link is True:
        query["gpi_auto_linked"] = True
    elif has_gpi_link is False:
        query["gpi_auto_linked"] = {"$ne": True}
    if has_s9_data is True:
        query["s9_ingested"] = True
    elif has_s9_data is False:
        query["s9_ingested"] = {"$ne": True}
    if search:
        query["$or"] = [
            {"file_name": {"$regex": search, "$options": "i"}},
            {"document_id": {"$regex": search, "$options": "i"}},
            {"vendor_truth": {"$regex": search, "$options": "i"}},
        ]

    total = await db[DOCS_COLL].count_documents(query)
    docs = await db[DOCS_COLL].find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total}


@router.get("/runs/{run_id}/documents/{doc_uid}")
async def get_document(run_id: str, doc_uid: str):
    db = get_db()
    doc = await db[DOCS_COLL].find_one({"run_id": run_id, "doc_uid": doc_uid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.put("/runs/{run_id}/documents/{doc_uid}")
async def update_document_scoring(run_id: str, doc_uid: str, req: UpdateDocScoringReq):
    db = get_db()
    doc = await db[DOCS_COLL].find_one({"run_id": run_id, "doc_uid": doc_uid})
    if not doc:
        raise HTTPException(404, "Document not found")

    updates = {}
    for k, v in req.dict().items():
        if v is not None:
            updates[k] = v

    # Track manual edits to GPI fields
    gpi_fields = {"gpi_doc_type", "gpi_vendor", "gpi_amount", "gpi_po", "gpi_folder_output", "gpi_needs_review", "gpi_final_status"}
    if any(k in updates for k in gpi_fields):
        updates["gpi_manually_edited"] = True

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db[DOCS_COLL].update_one({"run_id": run_id, "doc_uid": doc_uid}, {"$set": updates})

    # Re-fetch, auto-score, and apply
    doc = await db[DOCS_COLL].find_one({"run_id": run_id, "doc_uid": doc_uid})
    doc.pop("_id", None)
    scores = auto_score_correctness(doc)
    # Only apply auto-scored fields that weren't explicitly set in this request
    auto_apply = {k: v for k, v in scores.items() if k not in updates}
    if auto_apply:
        await db[DOCS_COLL].update_one({"run_id": run_id, "doc_uid": doc_uid}, {"$set": auto_apply})

    final = await db[DOCS_COLL].find_one({"run_id": run_id, "doc_uid": doc_uid}, {"_id": 0})
    return final


@router.delete("/runs/{run_id}/documents/{doc_uid}")
async def delete_document(run_id: str, doc_uid: str):
    db = get_db()
    result = await db[DOCS_COLL].delete_one({"run_id": run_id, "doc_uid": doc_uid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Document not found")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════
# GPI AUTO-POPULATE
# ═══════════════════════════════════════════════════════════════

@router.post("/runs/{run_id}/auto-populate")
async def auto_populate_gpi(run_id: str):
    """Auto-populate GPI fields from existing hub_documents collection."""
    db = get_db()
    docs = await db[DOCS_COLL].find({"run_id": run_id}, {"_id": 0}).to_list(1000)

    linked = 0
    for doc in docs:
        did = doc.get("document_id", "")
        fname = doc.get("file_name", "")
        if not did and not fname:
            continue

        # Try to find matching hub document
        hub_doc = None
        if did:
            hub_doc = await db.hub_documents.find_one(
                {"$or": [{"document_id": did}, {"doc_id": did}]},
                {"_id": 0}
            )
        if not hub_doc and fname:
            hub_doc = await db.hub_documents.find_one(
                {"file_name": {"$regex": re.escape(fname), "$options": "i"}},
                {"_id": 0}
            )

        if hub_doc:
            gpi_updates = {
                "gpi_ingested": True,
                "gpi_doc_type": hub_doc.get("document_type") or hub_doc.get("doc_type", ""),
                "gpi_vendor": hub_doc.get("vendor_name") or hub_doc.get("vendor_no", ""),
                "gpi_amount": hub_doc.get("total_amount") or hub_doc.get("invoice_amount"),
                "gpi_po": hub_doc.get("po_number") or hub_doc.get("purchase_order_number", ""),
                "gpi_folder_output": hub_doc.get("sharepoint_folder") or hub_doc.get("filed_to", ""),
                "gpi_auto_linked": True,
                "gpi_source_document_id": hub_doc.get("document_id") or hub_doc.get("doc_id", ""),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # Map status
            status = hub_doc.get("status", "")
            if status in ("Completed", "Filed", "Posted"):
                gpi_updates["gpi_final_status"] = "Usable"
                gpi_updates["gpi_needs_review"] = "None"
            elif status in ("Pending", "In_Review"):
                gpi_updates["gpi_final_status"] = "Partial"
                gpi_updates["gpi_needs_review"] = "Minor"
            elif status in ("Failed", "Error"):
                gpi_updates["gpi_final_status"] = "Failed"
                gpi_updates["gpi_needs_review"] = "Major"

            await db[DOCS_COLL].update_one(
                {"run_id": run_id, "doc_uid": doc["doc_uid"]},
                {"$set": gpi_updates}
            )
            linked += 1

    # Auto-score all docs in run
    all_docs = await db[DOCS_COLL].find({"run_id": run_id}).to_list(1000)
    for d in all_docs:
        d.pop("_id", None)
        scores = auto_score_correctness(d)
        if scores:
            await db[DOCS_COLL].update_one(
                {"run_id": run_id, "doc_uid": d["doc_uid"]},
                {"$set": scores}
            )

    # Update run status
    if linked > 0:
        await db[RUNS_COLL].update_one(
            {"run_id": run_id},
            {"$set": {"status": "in_progress", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )

    return {"linked": linked, "total": len(docs)}


# ═══════════════════════════════════════════════════════════════
# METRICS / SUMMARY
# ═══════════════════════════════════════════════════════════════

def _calc_metrics(docs):
    """Calculate KPIs for a list of bakeoff documents for both systems."""
    total = len(docs)
    if total == 0:
        return {"total": 0}

    def _sys_metrics(prefix):
        ingested = sum(1 for d in docs if d.get(f"{prefix}_ingested") is True)
        correct = lambda f: sum(1 for d in docs if d.get(f"{prefix}_{f}_correct") is True)
        scored = lambda f: sum(1 for d in docs if d.get(f"{prefix}_{f}_correct") is not None)

        no_touch = sum(1 for d in docs if _norm_str(d.get(f"{prefix}_needs_review")) == "none")
        usable = sum(1 for d in docs if _norm_str(d.get(f"{prefix}_final_status")) == "usable")
        partial = sum(1 for d in docs if _norm_str(d.get(f"{prefix}_final_status")) == "partial")
        failed = sum(1 for d in docs if _norm_str(d.get(f"{prefix}_final_status")) == "failed")

        def _pct(n, d):
            return round(n / d * 100, 1) if d > 0 else 0

        s_dt = scored("doc_type")
        s_v = scored("vendor")
        s_a = scored("amount")
        s_p = scored("po")
        s_f = scored("folder")

        return {
            "total_ingested": ingested,
            "ingest_rate": _pct(ingested, total),
            "classification_accuracy": _pct(correct("doc_type"), s_dt) if s_dt else None,
            "vendor_accuracy": _pct(correct("vendor"), s_v) if s_v else None,
            "amount_accuracy": _pct(correct("amount"), s_a) if s_a else None,
            "po_accuracy": _pct(correct("po"), s_p) if s_p else None,
            "folder_accuracy": _pct(correct("folder"), s_f) if s_f else None,
            "no_touch_rate": _pct(no_touch, total),
            "usable_output_rate": _pct(usable, total),
            "partial_rate": _pct(partial, total),
            "failed_rate": _pct(failed, total),
            "scored_count": max(s_dt, s_v, s_a, s_p, s_f),
        }

    return {
        "total": total,
        "gpi": _sys_metrics("gpi"),
        "s9": _sys_metrics("s9"),
    }


def _calc_breakdowns(docs):
    """Calculate breakdowns for why-wrong, by doc type, by vendor."""
    # Why-wrong tag distribution
    gpi_why = {}
    s9_why = {}
    for d in docs:
        for tag in (d.get("gpi_why_wrong_tags") or []):
            gpi_why[tag] = gpi_why.get(tag, 0) + 1
        for tag in (d.get("s9_why_wrong_tags") or []):
            s9_why[tag] = s9_why.get(tag, 0) + 1

    # By doc type
    by_doc_type = {}
    for d in docs:
        dt = d.get("doc_type_truth") or "Unknown"
        if dt not in by_doc_type:
            by_doc_type[dt] = {"total": 0, "gpi_correct": 0, "s9_correct": 0}
        by_doc_type[dt]["total"] += 1
        if d.get("gpi_doc_type_correct"):
            by_doc_type[dt]["gpi_correct"] += 1
        if d.get("s9_doc_type_correct"):
            by_doc_type[dt]["s9_correct"] += 1

    # By vendor
    by_vendor = {}
    for d in docs:
        v = d.get("vendor_truth") or "Unknown"
        if v not in by_vendor:
            by_vendor[v] = {"total": 0, "gpi_vendor_correct": 0, "s9_vendor_correct": 0}
        by_vendor[v]["total"] += 1
        if d.get("gpi_vendor_correct"):
            by_vendor[v]["gpi_vendor_correct"] += 1
        if d.get("s9_vendor_correct"):
            by_vendor[v]["s9_vendor_correct"] += 1

    # Key insights (deterministic)
    insights = []
    if gpi_why:
        top_gpi = max(gpi_why, key=gpi_why.get)
        insights.append(f"Top GPI failure mode: {top_gpi} ({gpi_why[top_gpi]} docs)")
    if s9_why:
        top_s9 = max(s9_why, key=s9_why.get)
        insights.append(f"Top Square 9 failure mode: {top_s9} ({s9_why[top_s9]} docs)")
    # Vendor with highest mismatch
    worst_vendor = None
    worst_rate = 0
    for v, data in by_vendor.items():
        if v == "Unknown" or data["total"] < 2:
            continue
        gpi_miss = data["total"] - data["gpi_vendor_correct"]
        if gpi_miss > worst_rate:
            worst_rate = gpi_miss
            worst_vendor = v
    if worst_vendor:
        insights.append(f"Vendor with highest GPI mismatch: {worst_vendor} ({worst_rate} mismatches)")

    return {
        "gpi_why_wrong": dict(sorted(gpi_why.items(), key=lambda x: -x[1])),
        "s9_why_wrong": dict(sorted(s9_why.items(), key=lambda x: -x[1])),
        "by_doc_type": by_doc_type,
        "by_vendor": by_vendor,
        "insights": insights,
    }


@router.get("/runs/{run_id}/metrics")
async def get_run_metrics(run_id: str):
    db = get_db()
    docs = await db[DOCS_COLL].find({"run_id": run_id}, {"_id": 0}).to_list(2000)
    metrics = _calc_metrics(docs)
    breakdowns = _calc_breakdowns(docs)
    return {"metrics": metrics, "breakdowns": breakdowns}


# ═══════════════════════════════════════════════════════════════
# EXPORT (Excel)
# ═══════════════════════════════════════════════════════════════

@router.get("/runs/{run_id}/export")
async def export_run(run_id: str):
    """Export run as Excel with two sheets: Documents + Summary."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    db = get_db()
    run = await db[RUNS_COLL].find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run not found")

    docs = await db[DOCS_COLL].find({"run_id": run_id}, {"_id": 0}).to_list(2000)
    metrics = _calc_metrics(docs)

    wb = Workbook()

    # --- Documents Sheet ---
    ws = wb.active
    ws.title = "Documents"
    headers = [
        "Document ID", "File Name", "Doc Type Truth", "Vendor Truth", "Amount Truth", "PO Truth", "Folder Truth",
        "GPI Ingested", "GPI Doc Type", "GPI Vendor", "GPI Amount", "GPI PO", "GPI Folder",
        "GPI DocType OK", "GPI Vendor OK", "GPI Amount OK", "GPI PO OK", "GPI Folder OK",
        "GPI Needs Review", "GPI Final Status", "GPI Why Wrong",
        "S9 Ingested", "S9 Doc Type", "S9 Vendor", "S9 Amount", "S9 PO", "S9 Folder",
        "S9 DocType OK", "S9 Vendor OK", "S9 Amount OK", "S9 PO OK", "S9 Folder OK",
        "S9 Needs Review", "S9 Final Status", "S9 Why Wrong",
    ]
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for i, d in enumerate(docs, 2):
        vals = [
            d.get("document_id"), d.get("file_name"),
            d.get("doc_type_truth"), d.get("vendor_truth"), d.get("amount_truth"), d.get("po_truth"), d.get("folder_truth"),
            d.get("gpi_ingested"), d.get("gpi_doc_type"), d.get("gpi_vendor"), d.get("gpi_amount"), d.get("gpi_po"), d.get("gpi_folder_output"),
            d.get("gpi_doc_type_correct"), d.get("gpi_vendor_correct"), d.get("gpi_amount_correct"), d.get("gpi_po_correct"), d.get("gpi_folder_correct"),
            d.get("gpi_needs_review"), d.get("gpi_final_status"), ", ".join(d.get("gpi_why_wrong_tags") or []),
            d.get("s9_ingested"), d.get("s9_doc_type"), d.get("s9_vendor"), d.get("s9_amount"), d.get("s9_po"), d.get("s9_folder_output"),
            d.get("s9_doc_type_correct"), d.get("s9_vendor_correct"), d.get("s9_amount_correct"), d.get("s9_po_correct"), d.get("s9_folder_correct"),
            d.get("s9_needs_review"), d.get("s9_final_status"), ", ".join(d.get("s9_why_wrong_tags") or []),
        ]
        for col, v in enumerate(vals, 1):
            ws.cell(row=i, column=col, value=v)

    # --- Summary Sheet ---
    ws2 = wb.create_sheet("Summary")
    ws2.cell(row=1, column=1, value=f"Bake-Off: {run.get('name', '')}").font = Font(bold=True, size=14)
    ws2.cell(row=2, column=1, value=f"Date: {run.get('test_date', '')}")
    ws2.cell(row=3, column=1, value=f"Documents: {metrics.get('total', 0)}")

    kpi_headers = ["KPI", "GPI Hub", "Square 9", "Delta"]
    for col, h in enumerate(kpi_headers, 1):
        cell = ws2.cell(row=5, column=col, value=h)
        cell.font = Font(bold=True)

    gpi = metrics.get("gpi", {})
    s9 = metrics.get("s9", {})
    kpis = [
        ("Ingest Rate %", gpi.get("ingest_rate"), s9.get("ingest_rate")),
        ("Classification Accuracy %", gpi.get("classification_accuracy"), s9.get("classification_accuracy")),
        ("Vendor Accuracy %", gpi.get("vendor_accuracy"), s9.get("vendor_accuracy")),
        ("Amount Accuracy %", gpi.get("amount_accuracy"), s9.get("amount_accuracy")),
        ("PO Accuracy %", gpi.get("po_accuracy"), s9.get("po_accuracy")),
        ("Folder Accuracy %", gpi.get("folder_accuracy"), s9.get("folder_accuracy")),
        ("No-Touch Rate %", gpi.get("no_touch_rate"), s9.get("no_touch_rate")),
        ("Usable Output Rate %", gpi.get("usable_output_rate"), s9.get("usable_output_rate")),
    ]
    for i, (label, g, s) in enumerate(kpis, 6):
        ws2.cell(row=i, column=1, value=label)
        ws2.cell(row=i, column=2, value=g)
        ws2.cell(row=i, column=3, value=s)
        if g is not None and s is not None:
            ws2.cell(row=i, column=4, value=round(g - s, 1))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"bakeoff_{run_id}_{run.get('name', 'export').replace(' ', '_')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/why-wrong-tags")
async def get_why_wrong_tags():
    return {"tags": WHY_WRONG_TAGS}
