"""
GPI Document Hub - Dashboard Aggregation Helpers

Authoritative implementation of document-type dashboard aggregation logic,
extracted from server.py during the "Shared Helper Extraction" remediation pass.

Consumed by routers/dashboard.py for both the JSON endpoint and CSV export.
"""

import logging
from typing import Dict, Optional

from deps import get_db

logger = logging.getLogger(__name__)


def _get_workflow_engine():
    """Lazy import to avoid circular dependency at module level."""
    from workflows.core.engine import WorkflowEngine
    return WorkflowEngine


async def aggregate_document_types_data(
    source_system: Optional[str] = None,
    doc_type: Optional[str] = None,
    classification: Optional[str] = None,
) -> Dict:
    """
    Shared aggregation logic for document types dashboard.
    Reused by both the JSON endpoint and CSV export endpoint.

    Args:
        source_system: Filter by source system (SQUARE9, ZETADOCS, GPI_HUB_NATIVE)
        doc_type: Filter by specific document type
        classification: Filter by classification method: "deterministic", "ai", "all"
    """
    db = get_db()
    WorkflowEngine = _get_workflow_engine()

    # Build base match filter
    base_match = {}
    if source_system:
        base_match["source_system"] = source_system
    if doc_type:
        base_match["doc_type"] = doc_type

    # Add classification filter
    if classification == "deterministic":
        base_match["$and"] = [
            {"classification_method": {"$exists": True}},
            {"classification_method": {"$not": {"$regex": "^ai:"}}}
        ]
    elif classification == "ai":
        base_match["classification_method"] = {"$regex": "^ai:"}

    # Aggregate status counts by doc_type
    status_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]},
                "workflow_status": {"$ifNull": ["$workflow_status", "none"]}
            },
            "count": {"$sum": 1}
        }}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(500)

    # Aggregate extraction field presence by doc_type
    extraction_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "total": {"$sum": 1},
            "has_vendor": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$vendor_raw", None]},
                {"$ne": ["$vendor_canonical", None]}
            ]}, 1, 0]}},
            "has_invoice_number": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$invoice_number_raw", None]},
                {"$ne": ["$invoice_number_clean", None]}
            ]}, 1, 0]}},
            "has_amount": {"$sum": {"$cond": [{"$ne": ["$amount_float", None]}, 1, 0]}},
            "has_po_number": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$po_number_raw", None]},
                {"$ne": ["$po_number_clean", None]}
            ]}, 1, 0]}},
            "has_due_date": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$due_date_raw", None]},
                {"$ne": ["$due_date_iso", None]}
            ]}, 1, 0]}},
            "avg_confidence": {"$avg": {"$ifNull": ["$ai_confidence", 0]}}
        }}
    ]
    extraction_results = await db.hub_documents.aggregate(extraction_pipeline).to_list(50)

    # Aggregate match_method distribution by doc_type
    match_method_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]},
                "match_method": {"$ifNull": ["$vendor_match_method", "none"]}
            },
            "count": {"$sum": 1}
        }}
    ]
    match_method_results = await db.hub_documents.aggregate(match_method_pipeline).to_list(200)

    # Aggregate source_system counts for the filter dropdown
    source_system_pipeline = [
        {"$group": {
            "_id": {"$ifNull": ["$source_system", "UNKNOWN"]},
            "count": {"$sum": 1}
        }}
    ]
    source_system_results = await db.hub_documents.aggregate(source_system_pipeline).to_list(20)

    # Aggregate classification method counts by doc_type
    classification_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "total": {"$sum": 1},
            "deterministic_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": [{"$ifNull": ["$classification_method", ""]}, ""]},
                    {"$not": [{"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}}]}
                ]},
                1, 0
            ]}},
            "ai_count": {"$sum": {"$cond": [
                {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}},
                1, 0
            ]}},
            "other_count": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": [{"$ifNull": ["$classification_method", ""]}, ""]},
                    {"$eq": ["$classification_method", None]}
                ]},
                1, 0
            ]}},
            "ai_assisted_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$ai_classification", None]},
                    {"$ne": [{"$ifNull": ["$doc_type", "OTHER"]}, "OTHER"]},
                    {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}}
                ]},
                1, 0
            ]}},
            "ai_suggested_but_rejected_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$ai_classification", None]},
                    {"$eq": [{"$ifNull": ["$doc_type", "OTHER"]}, "OTHER"]}
                ]},
                1, 0
            ]}}
        }}
    ]
    classification_results = await db.hub_documents.aggregate(classification_pipeline).to_list(50)

    # Build the response structure
    by_type = {}

    for dt in WorkflowEngine.get_all_doc_types():
        by_type[dt] = {
            "total": 0,
            "status_counts": {},
            "extraction": {
                "vendor": {"rate": 0.0, "count": 0},
                "invoice_number": {"rate": 0.0, "count": 0},
                "amount": {"rate": 0.0, "count": 0},
                "po_number": {"rate": 0.0, "count": 0},
                "due_date": {"rate": 0.0, "count": 0}
            },
            "match_methods": {},
            "avg_confidence": 0.0,
            "classification_counts": {
                "deterministic": 0,
                "ai": 0,
                "other": 0
            },
            "ai_assisted_count": 0,
            "ai_suggested_but_rejected_count": 0,
            "active_queue_count": 0
        }

    terminal_statuses = ["approved", "exported", "archived", "rejected", "failed"]

    # Populate status counts
    for r in status_results:
        dt = r["_id"]["doc_type"]
        status = r["_id"]["workflow_status"]
        count = r["count"]

        if dt not in by_type:
            by_type[dt] = {
                "total": 0,
                "status_counts": {},
                "extraction": {
                    "vendor": {"rate": 0.0, "count": 0},
                    "invoice_number": {"rate": 0.0, "count": 0},
                    "amount": {"rate": 0.0, "count": 0},
                    "po_number": {"rate": 0.0, "count": 0},
                    "due_date": {"rate": 0.0, "count": 0}
                },
                "match_methods": {},
                "avg_confidence": 0.0,
                "classification_counts": {"deterministic": 0, "ai": 0, "other": 0},
                "ai_assisted_count": 0,
                "ai_suggested_but_rejected_count": 0,
                "active_queue_count": 0
            }

        by_type[dt]["status_counts"][status] = count
        by_type[dt]["total"] += count

        if status not in terminal_statuses:
            by_type[dt]["active_queue_count"] += count

    # Populate extraction rates
    for r in extraction_results:
        dt = r["_id"]
        if dt not in by_type:
            continue

        total = r["total"] or 1
        by_type[dt]["extraction"]["vendor"]["count"] = r.get("has_vendor", 0)
        by_type[dt]["extraction"]["vendor"]["rate"] = round(r.get("has_vendor", 0) / total, 2)
        by_type[dt]["extraction"]["invoice_number"]["count"] = r.get("has_invoice_number", 0)
        by_type[dt]["extraction"]["invoice_number"]["rate"] = round(r.get("has_invoice_number", 0) / total, 2)
        by_type[dt]["extraction"]["amount"]["count"] = r.get("has_amount", 0)
        by_type[dt]["extraction"]["amount"]["rate"] = round(r.get("has_amount", 0) / total, 2)
        by_type[dt]["extraction"]["po_number"]["count"] = r.get("has_po_number", 0)
        by_type[dt]["extraction"]["po_number"]["rate"] = round(r.get("has_po_number", 0) / total, 2)
        by_type[dt]["extraction"]["due_date"]["count"] = r.get("has_due_date", 0)
        by_type[dt]["extraction"]["due_date"]["rate"] = round(r.get("has_due_date", 0) / total, 2)
        by_type[dt]["avg_confidence"] = round(r.get("avg_confidence", 0), 2)

    # Populate match methods
    for r in match_method_results:
        dt = r["_id"]["doc_type"]
        method = r["_id"]["match_method"]
        count = r["count"]

        if dt not in by_type:
            continue

        by_type[dt]["match_methods"][method] = count

    # Populate classification counts
    for r in classification_results:
        dt = r["_id"]
        if dt not in by_type:
            continue

        by_type[dt]["classification_counts"]["deterministic"] = r.get("deterministic_count", 0)
        by_type[dt]["classification_counts"]["ai"] = r.get("ai_count", 0)
        by_type[dt]["classification_counts"]["other"] = r.get("other_count", 0)
        by_type[dt]["ai_assisted_count"] = r.get("ai_assisted_count", 0)
        by_type[dt]["ai_suggested_but_rejected_count"] = r.get("ai_suggested_but_rejected_count", 0)

    # Build source system filter options
    source_systems = {r["_id"]: r["count"] for r in source_system_results}

    return {
        "by_type": by_type,
        "source_systems": source_systems,
        "source_system_filter": source_system,
        "doc_type_filter": doc_type,
        "classification_filter": classification,
    }
