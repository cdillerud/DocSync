"""
Dashboard endpoints: overall stats + per-doc-type dashboard + CSV export.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 6). No logic changed.
"""
from fastapi import APIRouter, Query
from fastapi.responses import Response
from typing import Optional, Dict
from datetime import datetime, timezone
import csv
import io

from core.db import db
from core import config
from services.workflow_engine import WorkflowEngine

router = APIRouter(prefix="/api")


@router.get("/dashboard/stats")
async def get_dashboard_stats():
    total = await db.hub_documents.count_documents({})
    by_status = {}
    for s in ["Received", "Classified", "LinkedToBC", "Exception", "Completed"]:
        by_status[s] = await db.hub_documents.count_documents({"status": s})
    by_type = {}
    for t in ["SalesOrder", "SalesInvoice", "PurchaseInvoice", "PurchaseOrder", "Shipment", "Receipt", "Other"]:
        count = await db.hub_documents.count_documents({"document_type": t})
        if count > 0:
            by_type[t] = count
    recent_workflows = await db.hub_workflow_runs.find({}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    failed_workflows = await db.hub_workflow_runs.find({"status": "Failed"}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    return {
        "total_documents": total, "by_status": by_status, "by_type": by_type,
        "recent_workflows": recent_workflows, "failed_workflows": failed_workflows,
        "demo_mode": config.DEMO_MODE
    }


async def _aggregate_document_types_data(
    source_system: Optional[str] = None,
    doc_type: Optional[str] = None,
    classification: Optional[str] = None
) -> Dict:
    """
    Shared aggregation logic for document types dashboard.
    Reused by both the JSON endpoint and CSV export endpoint.
    """
    base_match = {}
    if source_system:
        base_match["source_system"] = source_system
    if doc_type:
        base_match["doc_type"] = doc_type

    if classification == "deterministic":
        base_match["$and"] = [
            {"classification_method": {"$exists": True}},
            {"classification_method": {"$not": {"$regex": "^ai:"}}}
        ]
    elif classification == "ai":
        base_match["classification_method"] = {"$regex": "^ai:"}

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

    source_system_pipeline = [
        {"$group": {
            "_id": {"$ifNull": ["$source_system", "UNKNOWN"]},
            "count": {"$sum": 1}
        }}
    ]
    source_system_results = await db.hub_documents.aggregate(source_system_pipeline).to_list(20)

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

    for r in match_method_results:
        dt = r["_id"]["doc_type"]
        method = r["_id"]["match_method"]
        count = r["count"]

        if dt not in by_type:
            continue

        by_type[dt]["match_methods"][method] = count

    for r in classification_results:
        dt = r["_id"]
        if dt not in by_type:
            continue

        by_type[dt]["classification_counts"]["deterministic"] = r.get("deterministic_count", 0)
        by_type[dt]["classification_counts"]["ai"] = r.get("ai_count", 0)
        by_type[dt]["classification_counts"]["other"] = r.get("other_count", 0)
        by_type[dt]["ai_assisted_count"] = r.get("ai_assisted_count", 0)
        by_type[dt]["ai_suggested_but_rejected_count"] = r.get("ai_suggested_but_rejected_count", 0)

    source_systems = {r["_id"]: r["count"] for r in source_system_results}

    return {
        "by_type": by_type,
        "source_systems": source_systems,
        "source_system_filter": source_system,
        "doc_type_filter": doc_type,
        "classification_filter": classification
    }


@router.get("/dashboard/document-types")
async def get_document_types_dashboard(
    source_system: Optional[str] = Query(None, description="Filter by source_system: SQUARE9, ZETADOCS, GPI_HUB_NATIVE"),
    doc_type: Optional[str] = Query(None, description="Filter to specific doc_type"),
    classification: Optional[str] = Query(None, description="Filter by classification method: deterministic, ai, all")
):
    """
    Document Type Dashboard API.
    """
    classification_filter = classification if classification in ("deterministic", "ai") else None

    data = await _aggregate_document_types_data(source_system, doc_type, classification_filter)

    by_type = data["by_type"]
    source_systems = data["source_systems"]

    if not doc_type:
        by_type = {k: v for k, v in by_type.items() if v["total"] > 0}

    grand_total = sum(v["total"] for v in by_type.values())

    total_deterministic = sum(v.get("classification_counts", {}).get("deterministic", 0) for v in by_type.values())
    total_ai = sum(v.get("classification_counts", {}).get("ai", 0) for v in by_type.values())
    total_other = sum(v.get("classification_counts", {}).get("other", 0) for v in by_type.values())

    return {
        "by_type": by_type,
        "filters": {
            "source_system": source_system,
            "doc_type": doc_type,
            "classification": classification_filter
        },
        "source_systems_available": source_systems,
        "doc_types_available": list(by_type.keys()),
        "classification_methods_available": ["all", "deterministic", "ai"],
        "grand_total": grand_total,
        "classification_totals": {
            "deterministic": total_deterministic,
            "ai": total_ai,
            "other": total_other
        }
    }


@router.get("/dashboard/document-types/export")
async def export_document_types_dashboard(
    source_system: Optional[str] = Query(None, description="Filter by source_system"),
    doc_type: Optional[str] = Query(None, description="Filter by doc_type"),
    classification: Optional[str] = Query(None, description="Filter by classification method: deterministic, ai, all"),
    format: str = Query("csv", description="Export format (csv)")
):
    """
    Export Document Type Dashboard data as CSV.
    """
    classification_filter = classification if classification in ("deterministic", "ai") else None

    data = await _aggregate_document_types_data(source_system, doc_type, classification_filter)

    by_type = data["by_type"]
    source_system_filter = data["source_system_filter"] or "ALL"
    classification_filter_label = classification_filter or "ALL"

    if not doc_type:
        by_type = {k: v for k, v in by_type.items() if v["total"] > 0}

    output = io.StringIO()

    fieldnames = [
        'doc_type',
        'source_system',
        'classification_filter',
        'total',
        'status',
        'status_count',
        'vendor_extraction_rate',
        'invoice_number_extraction_rate',
        'amount_extraction_rate',
        'po_number_extraction_rate',
        'due_date_extraction_rate',
        'match_exact',
        'match_normalized',
        'match_alias',
        'match_fuzzy',
        'match_manual',
        'match_none',
        'classification_deterministic',
        'classification_ai',
        'classification_other',
        'ai_assisted_count',
        'ai_suggested_but_rejected_count'
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for dt, type_data in sorted(by_type.items()):
        extraction = type_data.get("extraction", {})
        match_methods = type_data.get("match_methods", {})
        classification_counts = type_data.get("classification_counts", {})

        common_fields = {
            'doc_type': dt,
            'source_system': source_system_filter,
            'classification_filter': classification_filter_label,
            'total': type_data.get("total", 0),
            'vendor_extraction_rate': extraction.get("vendor", {}).get("rate", 0),
            'invoice_number_extraction_rate': extraction.get("invoice_number", {}).get("rate", 0),
            'amount_extraction_rate': extraction.get("amount", {}).get("rate", 0),
            'po_number_extraction_rate': extraction.get("po_number", {}).get("rate", 0),
            'due_date_extraction_rate': extraction.get("due_date", {}).get("rate", 0),
            'match_exact': match_methods.get("exact", 0),
            'match_normalized': match_methods.get("normalized", 0),
            'match_alias': match_methods.get("alias", 0),
            'match_fuzzy': match_methods.get("fuzzy", 0),
            'match_manual': match_methods.get("manual", 0),
            'match_none': match_methods.get("none", 0),
            'classification_deterministic': classification_counts.get("deterministic", 0),
            'classification_ai': classification_counts.get("ai", 0),
            'classification_other': classification_counts.get("other", 0),
            'ai_assisted_count': type_data.get("ai_assisted_count", 0),
            'ai_suggested_but_rejected_count': type_data.get("ai_suggested_but_rejected_count", 0)
        }

        status_counts = type_data.get("status_counts", {})

        if not status_counts:
            writer.writerow({**common_fields, 'status': '', 'status_count': 0})
        else:
            for status, count in sorted(status_counts.items()):
                writer.writerow({**common_fields, 'status': status, 'status_count': count})

    csv_content = output.getvalue()
    output.close()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"document_types_dashboard_{timestamp}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
