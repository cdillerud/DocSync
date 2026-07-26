"""Compatibility API for the original /api/migration endpoints.

The newer SharePoint migration workflow lives under /api/migration/sharepoint.
These routes preserve the earlier migration POC contract used by operational
checks and older clients while keeping the implementation isolated from the
monolithic server module.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/migration", tags=["Legacy Migration Compatibility"])

SUPPORTED_DOC_TYPES = [
    "AP_INVOICE",
    "SALES_INVOICE",
    "PURCHASE_ORDER",
    "STATEMENT",
    "QUALITY_DOC",
]
SOURCE_SYSTEMS = ["SQUARE9", "ZETADOCS"]

ZETADOCS_MAPPINGS = {
    "Purchase Invoice": "AP_INVOICE",
    "Sales Invoice": "SALES_INVOICE",
    "Purchase Order": "PURCHASE_ORDER",
}
SQUARE9_MAPPINGS = {
    "AP Invoice": "AP_INVOICE",
    "Customer Invoice": "SALES_INVOICE",
    "PO": "PURCHASE_ORDER",
    "Statement": "STATEMENT",
    "Quality": "QUALITY_DOC",
}

_SAMPLE_LEGACY_DOCUMENTS = [
    {
        "legacy_id": "square9-ap-001",
        "file_name": "invoice-1001.pdf",
        "source_system": "SQUARE9",
        "legacy_type": "AP Invoice",
        "doc_type": "AP_INVOICE",
    },
    {
        "legacy_id": "zetadocs-sales-001",
        "file_name": "sales-invoice-5001.pdf",
        "source_system": "ZETADOCS",
        "legacy_type": "Sales Invoice",
        "doc_type": "SALES_INVOICE",
    },
    {
        "legacy_id": "square9-po-001",
        "file_name": "purchase-order-001.pdf",
        "source_system": "SQUARE9",
        "legacy_type": "PO",
        "doc_type": "PURCHASE_ORDER",
    },
    {
        "legacy_id": "zetadocs-statement-001",
        "file_name": "vendor-statement.pdf",
        "source_system": "ZETADOCS",
        "legacy_type": "Statement",
        "doc_type": "STATEMENT",
    },
    {
        "legacy_id": "square9-quality-001",
        "file_name": "quality-certificate.pdf",
        "source_system": "SQUARE9",
        "legacy_type": "Quality",
        "doc_type": "QUALITY_DOC",
    },
]


class MigrationRunRequest(BaseModel):
    mode: str = "dry_run"
    source_filter: Optional[str] = None
    limit: int = 100


def _active_database(request: Request):
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return database


def _filtered_samples(source_filter: Optional[str], limit: int) -> list[dict[str, Any]]:
    docs = _SAMPLE_LEGACY_DOCUMENTS
    if source_filter:
        source = source_filter.upper()
        if source not in SOURCE_SYSTEMS:
            raise HTTPException(status_code=400, detail=f"Unknown source_filter: {source_filter}")
        docs = [doc for doc in docs if doc["source_system"] == source]
    return [dict(doc) for doc in docs[: max(0, limit)]]


def _preview_document(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "legacy": {
            "id": doc["legacy_id"],
            "file_name": doc["file_name"],
            "metadata": {
                "legacy_system": doc["source_system"],
                "legacy_type": doc["legacy_type"],
            },
        },
        "preview": {
            "doc_type": doc["doc_type"],
            "source_system": doc["source_system"],
            "capture_channel": "MIGRATION",
            "workflow_status": "Received",
        },
    }


def _hub_document(doc: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "legacy_id": doc["legacy_id"],
        "legacy_system": doc["source_system"],
        "file_name": doc["file_name"],
        "doc_type": doc["doc_type"],
        "document_type": doc["doc_type"],
        "source_system": doc["source_system"],
        "capture_channel": "MIGRATION",
        "source": "migration",
        "status": "Received",
        "workflow_status": "Received",
        "workflow_history": [
            {
                "event": "MIGRATED_FROM_LEGACY",
                "timestamp": now,
                "source_system": doc["source_system"],
            }
        ],
        "is_migrated": True,
        "created_utc": now,
        "updated_utc": now,
    }


@router.get("/supported-types")
async def supported_types():
    return {
        "supported_doc_types": SUPPORTED_DOC_TYPES,
        "source_systems": SOURCE_SYSTEMS,
        "zetadocs_mappings": ZETADOCS_MAPPINGS,
        "square9_mappings": SQUARE9_MAPPINGS,
    }


@router.get("/preview")
async def preview_migration(
    source_filter: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=500),
):
    docs = _filtered_samples(source_filter, limit)
    return {
        "source_name": "legacy-migration-sample",
        "total_count": len(_filtered_samples(source_filter, 500)),
        "preview_count": len(docs),
        "documents": [_preview_document(doc) for doc in docs],
        "filters": {"source_filter": source_filter, "limit": limit},
    }


@router.post("/run")
async def run_migration(payload: MigrationRunRequest, request: Request):
    mode = payload.mode.lower()
    if mode not in {"dry_run", "real"}:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {payload.mode}")

    docs = _filtered_samples(payload.source_filter, payload.limit)
    sample_documents = [_hub_document(doc) for doc in docs]
    skipped = 0
    errors: list[str] = []

    if mode == "real":
        database = _active_database(request)
        inserted_documents: list[dict[str, Any]] = []
        for source_doc, hub_doc in zip(docs, sample_documents):
            try:
                existing = await database.hub_documents.find_one(
                    {"legacy_id": source_doc["legacy_id"]}, {"_id": 1}
                )
                if existing:
                    skipped += 1
                    continue
                await database.hub_documents.insert_one(dict(hub_doc))
                inserted_documents.append(hub_doc)
            except Exception as exc:  # return per-document stats instead of aborting batch
                errors.append(f"{source_doc['legacy_id']}: {exc}")
        sample_documents = inserted_documents

    by_doc_type = Counter(doc["doc_type"] for doc in docs)
    by_source = Counter(doc["source_system"] for doc in docs)
    by_status = Counter("Received" for _ in docs)
    success_count = len(docs) - skipped - len(errors)

    return {
        "mode": mode,
        "stats": {
            "total_processed": len(docs),
            "total_success": max(0, success_count),
            "total_skipped": skipped,
            "total_errors": len(errors),
            "by_doc_type": dict(by_doc_type),
            "by_source_system": dict(by_source),
            "by_workflow_status": dict(by_status),
        },
        "sample_documents": sample_documents,
        "errors": errors,
    }


@router.get("/stats")
async def migration_stats(request: Request):
    database = _active_database(request)
    query = {"is_migrated": True}
    total = await database.hub_documents.count_documents(query)

    async def grouped(field: str) -> dict[str, int]:
        pipeline = [
            {"$match": query},
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        ]
        rows = await database.hub_documents.aggregate(pipeline).to_list(100)
        return {str(row.get("_id") or "UNKNOWN"): int(row["count"]) for row in rows}

    return {
        "total_migrated": int(total),
        "by_legacy_system": await grouped("legacy_system"),
        "by_doc_type": await grouped("doc_type"),
        "by_workflow_status": await grouped("workflow_status"),
    }


@router.post("/generate-sample")
async def generate_sample(output_path: str = Query("/tmp/docsync_migration_sample.json")):
    path = Path(output_path).expanduser()
    allowed_roots = (Path("/tmp"), Path("/app/backend/data"))
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="output_path must be under /tmp or /app/backend/data")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"documents": _SAMPLE_LEGACY_DOCUMENTS}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "success": True,
        "path": str(path),
        "message": f"Generated {len(_SAMPLE_LEGACY_DOCUMENTS)} sample migration records",
    }
