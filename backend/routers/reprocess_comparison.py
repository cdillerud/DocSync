"""
GPI Document Hub — Reprocess Comparison Router

Re-runs the improved LLM pipeline on all existing documents and compares
old vs new results WITHOUT overwriting production data.

The comparison stores:
  - Before snapshot (doc_type, vendor, confidence, PO, amounts, etc.)
  - After snapshot (re-classified results)
  - Delta analysis (improved, regressed, unchanged for each field)
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import APIRouter, Query, BackgroundTasks
from deps import get_db

logger = logging.getLogger("reprocess_comparison")

router = APIRouter(prefix="/reprocess-comparison", tags=["Reprocess Comparison"])

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))

# Module-level run state
_current_run: Dict[str, Any] = {"status": "idle"}


def _snapshot_doc(doc: dict) -> dict:
    """Extract the classification/extraction fields we want to compare."""
    ef = doc.get("extracted_fields") or {}
    return {
        "doc_type": doc.get("suggested_job_type") or doc.get("document_type") or "Unknown",
        "confidence": round(float(doc.get("ai_confidence") or doc.get("classification_confidence") or 0), 3),
        "vendor_raw": doc.get("vendor_raw") or ef.get("vendor") or ef.get("vendor_name") or "",
        "vendor_no": doc.get("vendor_no") or "",
        "vendor_canonical": doc.get("vendor_canonical") or "",
        "vendor_match_method": doc.get("vendor_match_method") or doc.get("match_method") or "",
        "po_number": ef.get("po_number") or ef.get("purchase_order_number") or doc.get("po_number") or "",
        "invoice_number": ef.get("invoice_number") or "",
        "total_amount": ef.get("total_amount") or ef.get("amount") or "",
        "line_items_count": len(ef.get("line_items") or []),
        "model": doc.get("ai_model") or doc.get("classification_method") or "",
        "routing_flags": {
            "is_international": ef.get("is_international"),
            "is_credit_memo": ef.get("is_credit_memo"),
            "freight_direction": ef.get("freight_direction"),
        },
    }


def _compare_snapshots(before: dict, after: dict) -> dict:
    """Compare before/after snapshots and compute delta."""
    changes = {}
    improved = 0
    regressed = 0
    unchanged = 0

    # Doc type
    if before["doc_type"] != after["doc_type"]:
        changes["doc_type"] = {"before": before["doc_type"], "after": after["doc_type"]}
    else:
        unchanged += 1

    # Confidence
    conf_delta = after["confidence"] - before["confidence"]
    if abs(conf_delta) > 0.01:
        changes["confidence"] = {
            "before": before["confidence"],
            "after": after["confidence"],
            "delta": round(conf_delta, 3),
        }
        if conf_delta > 0:
            improved += 1
        else:
            regressed += 1
    else:
        unchanged += 1

    # Vendor
    if before["vendor_raw"] != after["vendor_raw"]:
        changes["vendor_raw"] = {"before": before["vendor_raw"], "after": after["vendor_raw"]}

    if before["vendor_no"] != after["vendor_no"]:
        changes["vendor_no"] = {"before": before["vendor_no"], "after": after["vendor_no"]}

    # PO number
    if str(before["po_number"]) != str(after["po_number"]):
        changes["po_number"] = {"before": before["po_number"], "after": after["po_number"]}

    # Invoice number
    if str(before["invoice_number"]) != str(after["invoice_number"]):
        changes["invoice_number"] = {"before": before["invoice_number"], "after": after["invoice_number"]}

    # Total amount
    if str(before["total_amount"]) != str(after["total_amount"]):
        changes["total_amount"] = {"before": before["total_amount"], "after": after["total_amount"]}

    # Line items count
    li_delta = after["line_items_count"] - before["line_items_count"]
    if li_delta != 0:
        changes["line_items_count"] = {
            "before": before["line_items_count"],
            "after": after["line_items_count"],
            "delta": li_delta,
        }
        if li_delta > 0:
            improved += 1
        else:
            regressed += 1

    has_changes = len(changes) > 0
    return {
        "has_changes": has_changes,
        "changes": changes,
        "fields_improved": improved,
        "fields_regressed": regressed,
        "fields_unchanged": unchanged,
    }


async def _run_comparison(run_id: str, limit: int, doc_type_filter: str):
    """Background task: re-classify all docs and compare."""
    global _current_run
    db = get_db()

    query: Dict[str, Any] = {}
    if doc_type_filter:
        query["suggested_job_type"] = doc_type_filter

    total = await db.hub_documents.count_documents(query)
    if total == 0:
        _current_run = {
            "status": "completed",
            "run_id": run_id,
            "total": 0,
            "processed": 0,
            "error": "No documents found to reprocess",
        }
        return

    actual_limit = min(limit, total)
    _current_run = {
        "status": "running",
        "run_id": run_id,
        "total": actual_limit,
        "processed": 0,
        "improved": 0,
        "regressed": 0,
        "unchanged": 0,
        "errors": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store run metadata
    await db.reprocess_comparison_runs.insert_one({
        "run_id": run_id,
        "status": "running",
        "total": actual_limit,
        "filter": doc_type_filter or "all",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    cursor = db.hub_documents.find(query, {"_id": 0}).limit(actual_limit)
    docs = await cursor.to_list(actual_limit)

    results = []

    for i, doc in enumerate(docs):
        doc_id = doc.get("id", "?")
        file_name = doc.get("file_name", "unknown.pdf")

        try:
            before = _snapshot_doc(doc)

            # Check if file exists on disk
            file_path = UPLOAD_DIR / doc_id
            if not file_path.exists():
                # Try alternate paths
                alt_path = UPLOAD_DIR / file_name
                if alt_path.exists():
                    file_path = alt_path
                else:
                    results.append({
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "status": "skipped",
                        "reason": "file_not_on_disk",
                        "before": before,
                    })
                    _current_run["errors"] += 1
                    _current_run["processed"] = i + 1
                    continue

            # Re-run classification pipeline
            from services.classification_pipeline import stage_classify_llm
            llm_result = await stage_classify_llm(
                str(file_path), file_name,
                doc.get("page_count", 1),
                doc=doc,
            )

            if llm_result.status.value != "passed":
                results.append({
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "status": "error",
                    "reason": llm_result.error or "classification_failed",
                    "before": before,
                })
                _current_run["errors"] += 1
                _current_run["processed"] = i + 1
                continue

            # Build "after" snapshot from LLM results
            llm_data = llm_result.data or {}
            llm_ef = llm_data.get("llm_extracted_fields", {})
            after = {
                "doc_type": llm_data.get("document_type", "Unknown"),
                "confidence": round(float(llm_data.get("confidence", 0)), 3),
                "vendor_raw": llm_ef.get("vendor") or llm_ef.get("vendor_name") or "",
                "vendor_no": "",  # vendor match not re-run here
                "vendor_canonical": "",
                "vendor_match_method": "",
                "po_number": llm_ef.get("po_number") or llm_ef.get("purchase_order_number") or "",
                "invoice_number": llm_ef.get("invoice_number") or "",
                "total_amount": llm_ef.get("total_amount") or llm_ef.get("amount") or "",
                "line_items_count": len(llm_ef.get("line_items") or []),
                "model": llm_data.get("method", "gemini-3-pro-preview"),
                "routing_flags": {
                    "is_international": llm_ef.get("is_international"),
                    "is_credit_memo": llm_ef.get("is_credit_memo"),
                    "freight_direction": llm_ef.get("freight_direction"),
                },
            }

            delta = _compare_snapshots(before, after)

            result_entry = {
                "doc_id": doc_id,
                "file_name": file_name,
                "status": "compared",
                "before": before,
                "after": after,
                "delta": delta,
            }
            results.append(result_entry)

            if delta["has_changes"]:
                if delta["fields_improved"] > delta["fields_regressed"]:
                    _current_run["improved"] += 1
                elif delta["fields_regressed"] > delta["fields_improved"]:
                    _current_run["regressed"] += 1
                else:
                    _current_run["unchanged"] += 1
            else:
                _current_run["unchanged"] += 1

        except Exception as e:
            logger.error("Comparison failed for doc %s: %s", doc_id, e)
            results.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "status": "error",
                "reason": str(e),
            })
            _current_run["errors"] += 1

        _current_run["processed"] = i + 1

        # Small delay to avoid rate limiting
        if (i + 1) % 5 == 0:
            await asyncio.sleep(1)

    # Compute summary
    total_processed = len([r for r in results if r["status"] == "compared"])
    total_changed = len([r for r in results if r.get("delta", {}).get("has_changes")])

    # Aggregate field-level changes
    field_change_counts = {}
    for r in results:
        if r.get("delta", {}).get("has_changes"):
            for field in r["delta"]["changes"]:
                field_change_counts[field] = field_change_counts.get(field, 0) + 1

    # Confidence distribution
    conf_deltas = []
    for r in results:
        d = r.get("delta", {}).get("changes", {}).get("confidence")
        if d:
            conf_deltas.append(d["delta"])

    avg_conf_delta = round(sum(conf_deltas) / len(conf_deltas), 3) if conf_deltas else 0

    summary = {
        "total_documents": actual_limit,
        "processed": total_processed,
        "skipped": len([r for r in results if r["status"] == "skipped"]),
        "errors": len([r for r in results if r["status"] == "error"]),
        "changed": total_changed,
        "unchanged": total_processed - total_changed,
        "improved": _current_run["improved"],
        "regressed": _current_run["regressed"],
        "field_change_counts": field_change_counts,
        "avg_confidence_delta": avg_conf_delta,
        "confidence_improved_count": len([d for d in conf_deltas if d > 0]),
        "confidence_regressed_count": len([d for d in conf_deltas if d < 0]),
    }

    finished_at = datetime.now(timezone.utc).isoformat()

    # Store results in DB
    await db.reprocess_comparison_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "status": "completed",
            "summary": summary,
            "finished_at": finished_at,
        }},
    )

    # Store individual results
    for r in results:
        r["run_id"] = run_id
    if results:
        await db.reprocess_comparison_results.insert_many(results)

    _current_run = {
        "status": "completed",
        "run_id": run_id,
        **summary,
        "started_at": _current_run.get("started_at"),
        "finished_at": finished_at,
    }

    logger.info(
        "Comparison run %s complete: %d docs, %d changed, %d improved, %d regressed",
        run_id, total_processed, total_changed, _current_run["improved"], _current_run["regressed"],
    )


@router.post("/run")
async def start_comparison(
    background_tasks: BackgroundTasks,
    limit: int = Query(500, ge=1, le=5000, description="Max documents to process"),
    doc_type: str = Query("", description="Filter by document type (empty = all)"),
):
    """Start a before/after comparison run. Runs in the background."""
    global _current_run

    if _current_run.get("status") == "running":
        return {
            "error": "A comparison is already running",
            "run_id": _current_run.get("run_id"),
            "processed": _current_run.get("processed", 0),
            "total": _current_run.get("total", 0),
        }

    run_id = f"cmp-{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(_run_comparison, run_id, limit, doc_type)

    return {
        "run_id": run_id,
        "status": "started",
        "limit": limit,
        "filter": doc_type or "all",
    }


@router.get("/status")
async def comparison_status():
    """Get the status of the current or last comparison run."""
    return _current_run


@router.get("/results/{run_id}")
async def comparison_results(
    run_id: str,
    changes_only: bool = Query(False, description="Only show documents with changes"),
):
    """Get detailed results of a comparison run."""
    db = get_db()

    run_meta = await db.reprocess_comparison_runs.find_one(
        {"run_id": run_id}, {"_id": 0}
    )
    if not run_meta:
        return {"error": "Run not found"}

    query: Dict[str, Any] = {"run_id": run_id}
    if changes_only:
        query["delta.has_changes"] = True

    results = await db.reprocess_comparison_results.find(
        query, {"_id": 0}
    ).to_list(5000)

    return {
        "run": run_meta,
        "results": results,
        "total_results": len(results),
    }


@router.get("/runs")
async def list_comparison_runs():
    """List all comparison runs."""
    db = get_db()
    runs = await db.reprocess_comparison_runs.find(
        {}, {"_id": 0}
    ).sort("started_at", -1).limit(20).to_list(20)
    return {"runs": runs}
