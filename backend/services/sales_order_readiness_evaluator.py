"""
GPI Document Hub — Sales Order Readiness Evaluator

Runs the readiness reviewer against historical sales orders in batch,
compares outputs against known outcomes (posted, corrected, failed),
and stores structured evaluation results for analysis.

EVALUATION ONLY: Never changes workflow behavior or posting decisions.

Collections:
  - so_readiness_evaluations   (one doc per evaluation run)
  - so_readiness_eval_details  (one doc per evaluated document)
"""

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Known outcome proxy fields on hub_documents
OUTCOME_FIELDS = {
    "posted_to_bc":        lambda d: bool(d.get("bc_sales_order", {}).get("success")),
    "manual_correction":   lambda d: bool(d.get("sales_review_status") == "corrected"
                                          or d.get("manual_so_correction")),
    "validation_failed":   lambda d: (d.get("validation_results") or {}).get("all_passed") is False,
    "had_customer_profile": None,  # filled during evaluation
    "auto_created":        lambda d: bool(d.get("auto_create_attempted") and d.get("bc_sales_order")),
}


async def run_batch_evaluation(
    db,
    limit: int = 100,
    doc_type_filter: Optional[List[str]] = None,
    status_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run the readiness reviewer against a batch of historical sales documents,
    compare against known outcomes, and store results.

    Args:
        db: Motor database
        limit: Max docs to evaluate
        doc_type_filter: Only these doc_types (default: all sales types)
        status_filter: Only these statuses (default: any)

    Returns:
        Summary dict with run_id, counts, and aggregate metrics.
    """
    from services.sales_order_readiness_reviewer import review_sales_order_readiness

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_started = datetime.now(timezone.utc).isoformat()

    # Build query for sales-type documents
    sales_types = doc_type_filter or [
        "SALES_INVOICE", "SALES_ORDER", "Sales_Order", "SalesOrder", "SalesInvoice",
    ]
    query: Dict[str, Any] = {"doc_type": {"$in": sales_types}}
    if status_filter:
        query["status"] = {"$in": status_filter}

    docs = await db.hub_documents.find(
        query, {"_id": 0}
    ).sort("created_utc", -1).limit(limit).to_list(limit)

    if not docs:
        # Fallback: try broader match including workflow_status or document_type
        docs = await db.hub_documents.find(
            {"$or": [
                {"doc_type": {"$in": sales_types}},
                {"document_type": {"$in": sales_types}},
                {"suggested_job_type": {"$in": ["Sales_Order", "SalesOrder"]}},
            ]},
            {"_id": 0}
        ).sort("created_utc", -1).limit(limit).to_list(limit)

    # Evaluate each document
    details: List[Dict[str, Any]] = []
    status_dist = Counter()
    total_confidence = 0.0
    total_latency = 0
    warning_counter = Counter()
    pattern_counter = Counter()
    no_profile_count = 0
    posted_cleanly_count = 0
    posted_total = 0

    for doc in docs:
        doc_id = doc.get("id", "")
        if not doc_id:
            continue

        # Load customer profile if available
        customer_no = (doc.get("matched_customer_no") or doc.get("customer_no")
                       or doc.get("bc_customer_number") or "")
        customer_name = (doc.get("customer_extracted")
                         or (doc.get("normalized_fields") or {}).get("customer")
                         or (doc.get("extracted_fields") or {}).get("customer") or "")

        customer_profile = None
        if customer_no:
            customer_profile = await db.customer_posting_profiles.find_one(
                {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
            )

        has_profile = customer_profile is not None
        if not has_profile:
            no_profile_count += 1

        # Build extracted order from document
        ef = doc.get("extracted_fields") or {}
        nf = doc.get("normalized_fields") or {}
        extracted_order = {
            "customer_name": customer_name,
            "customer_number": customer_no,
            "order_number": nf.get("order_number") or nf.get("invoice_number_clean") or ef.get("order_number"),
            "po_number": nf.get("customer_po") or nf.get("po_number") or ef.get("po_number"),
            "order_date": nf.get("order_date") or nf.get("invoice_date") or ef.get("order_date"),
            "ship_to_name": nf.get("ship_to") or nf.get("ship_to_name") or ef.get("ship_to_name"),
            "total_amount": doc.get("amount_float") or nf.get("amount_float") or ef.get("amount"),
            "line_items": nf.get("line_items") or doc.get("line_items") or ef.get("line_items") or [],
        }

        # Run readiness review
        try:
            review = await review_sales_order_readiness(
                extracted_order=extracted_order,
                customer_profile=customer_profile,
                validation_results=doc.get("validation_results"),
                document_context={"doc_id": doc_id, "doc_type": doc.get("doc_type"), "file_name": doc.get("file_name")},
            )
        except Exception as exc:
            logger.warning("[SOEval] Review failed for %s: %s", doc_id[:8], exc)
            details.append({
                "document_id": doc_id,
                "customer_id": customer_no,
                "customer_name": customer_name,
                "error": str(exc)[:200],
                "run_id": run_id,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            })
            continue

        # Extract known outcomes
        outcomes = {}
        for key, extractor in OUTCOME_FIELDS.items():
            if key == "had_customer_profile":
                outcomes[key] = has_profile
            elif extractor:
                outcomes[key] = extractor(doc)
            else:
                outcomes[key] = None

        if outcomes.get("posted_to_bc") or outcomes.get("auto_created"):
            posted_total += 1
            if review.readiness_status == "ready":
                posted_cleanly_count += 1

        # Aggregate metrics
        status_dist[review.readiness_status] += 1
        total_confidence += review.confidence
        total_latency += review.latency_ms

        for w in review.warnings:
            warning_counter[w] += 1
        for p in review.unusual_patterns:
            pattern_counter[p] += 1

        # Store detail record
        detail = {
            "run_id": run_id,
            "document_id": doc_id,
            "customer_id": customer_no,
            "customer_name": customer_name,
            "reviewer_readiness_status": review.readiness_status,
            "reviewer_confidence": review.confidence,
            "reviewer_summary": review.summary,
            "profile_match_count": len(review.profile_matches),
            "blocking_issue_count": len(review.blocking_issues),
            "warning_count": len(review.warnings),
            "unusual_pattern_count": len(review.unusual_patterns),
            "blocking_issues": review.blocking_issues,
            "warnings": review.warnings,
            "unusual_patterns": review.unusual_patterns,
            "profile_matches": review.profile_matches,
            "recommended_next_step": review.recommended_next_step,
            "model_used": review.model_used,
            "latency_ms": review.latency_ms,
            "schema_valid": review.schema_valid,
            "retry_count": review.retry_count,
            "had_customer_profile": has_profile,
            "known_outcomes": outcomes,
            "doc_status": doc.get("status"),
            "doc_workflow_status": doc.get("workflow_status"),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        details.append(detail)

    # Store details
    if details:
        await db.so_readiness_eval_details.insert_many(details)

    n = len(details)
    avg_confidence = round(total_confidence / max(n, 1), 4)
    avg_latency = round(total_latency / max(n, 1))

    # Build summary
    summary = {
        "run_id": run_id,
        "run_started": run_started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": n,
        "status_distribution": dict(status_dist),
        "avg_confidence": avg_confidence,
        "avg_latency_ms": avg_latency,
        "no_customer_profile_pct": round(no_profile_count / max(n, 1) * 100, 1),
        "posted_cleanly_pct": round(posted_cleanly_count / max(posted_total, 1) * 100, 1) if posted_total else None,
        "posted_total": posted_total,
        "top_warnings": [{"text": w, "count": c} for w, c in warning_counter.most_common(10)],
        "top_unusual_patterns": [{"text": p, "count": c} for p, c in pattern_counter.most_common(10)],
    }

    await db.so_readiness_evaluations.insert_one({**summary})
    # Remove _id from returned dict
    summary.pop("_id", None)

    logger.info(
        "[SOEval] Run %s complete: %d evaluated, dist=%s, avg_conf=%.2f, avg_lat=%dms",
        run_id, n, dict(status_dist), avg_confidence, avg_latency,
    )
    return summary


async def get_evaluation_runs(db, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent evaluation run summaries."""
    cursor = db.so_readiness_evaluations.find(
        {}, {"_id": 0}
    ).sort("run_started", -1).limit(limit)
    return await cursor.to_list(limit)


async def get_evaluation_details(
    db, run_id: str, limit: int = 100
) -> List[Dict[str, Any]]:
    """Fetch per-document details for a specific evaluation run."""
    cursor = db.so_readiness_eval_details.find(
        {"run_id": run_id}, {"_id": 0}
    ).limit(limit)
    return await cursor.to_list(limit)
