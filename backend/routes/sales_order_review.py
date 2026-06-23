"""Reviewer-facing API endpoints for customer sales-order intake.

This module registers endpoints on the existing ``sales_router`` so the current
``server.py`` does not need another direct router import.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

import sales_module
from services.business_central_service import get_bc_service
from services.sales_order_enrichment_runtime import (
    batch_enriched_preflight_pending,
    enrich_and_persist_sales_order_document,
    run_enriched_shadow_preflight,
)
from services.sales_order_review_service import (
    SalesOrderDocumentNotFound,
    approve_candidate,
    create_draft_order,
    list_review_queue,
    locate_document,
    reject_candidate,
    writes_enabled,
)

router = sales_module.sales_router


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=2000)


class RejectionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


def _db():
    if sales_module._db is None:
        raise HTTPException(
            status_code=503,
            detail="Sales database is not initialized",
        )
    return sales_module._db


def _not_found(document_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"Sales-order document {document_id} was not found",
    )


@router.get("/order-intake/status")
async def get_order_intake_status():
    """Return the current safety mode for sales-order intake."""

    return {
        "write_enabled": writes_enabled(),
        "mode": "write" if writes_enabled() else "shadow",
        "message": (
            "Business Central draft creation is enabled"
            if writes_enabled()
            else (
                "Customer, item, and existing-order enrichment are enabled; "
                "Business Central writes are disabled"
            )
        ),
    }


@router.get("/order-intake/review")
async def get_order_intake_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    refresh_missing: bool = Query(default=False),
):
    """List customer sales orders requiring review.

    Queue reads are nonblocking by default. When ``refresh_missing`` is explicitly
    true, documents without a stored preflight are evaluated and persisted before
    the queue is returned. Bulk preflight should normally use the dedicated
    ``preflight-pending`` endpoint instead.
    """

    return {
        "write_enabled": writes_enabled(),
        "mode": "write" if writes_enabled() else "shadow",
        "documents": await list_review_queue(
            _db(),
            limit=limit,
            refresh_missing=refresh_missing,
        ),
    }


@router.get("/order-intake/{document_id}")
async def get_order_intake_document(
    document_id: str,
    refresh_preflight: bool = Query(default=True),
):
    """Return the source document and its enriched deterministic candidate."""

    try:
        preflight = (
            await run_enriched_shadow_preflight(_db(), document_id)
            if refresh_preflight
            else None
        )
        located = await locate_document(_db(), document_id)
    except SalesOrderDocumentNotFound:
        raise _not_found(document_id)

    return {
        "document_id": document_id,
        "collection": located.collection_name,
        "write_enabled": writes_enabled(),
        "document": located.document,
        "enrichment": located.document.get("sales_order_enrichment") or {},
        "preflight": preflight or located.document.get(
            "sales_order_preflight"
        ),
    }


@router.post("/order-intake/preflight-pending")
async def preflight_pending_orders(
    limit: int = Query(default=100, ge=1, le=500),
):
    """Enrich, evaluate, and persist pending orders without writing to BC."""

    return await batch_enriched_preflight_pending(_db(), limit=limit)


@router.post("/order-intake/{document_id}/preflight")
async def preflight_order(document_id: str):
    """Enrich and evaluate a single sales-order candidate."""

    try:
        return await run_enriched_shadow_preflight(_db(), document_id)
    except SalesOrderDocumentNotFound:
        raise _not_found(document_id)


@router.post("/order-intake/{document_id}/approve")
async def approve_order(document_id: str, request: ApprovalRequest):
    """Record human approval and rerun enriched deterministic preflight."""

    try:
        await enrich_and_persist_sales_order_document(_db(), document_id)
        return await approve_candidate(
            _db(),
            document_id,
            reviewer=request.reviewer,
            note=request.note,
        )
    except SalesOrderDocumentNotFound:
        raise _not_found(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/order-intake/{document_id}/reject")
async def reject_order(document_id: str, request: RejectionRequest):
    """Reject a candidate and preserve the review reason."""

    try:
        return await reject_candidate(
            _db(),
            document_id,
            reviewer=request.reviewer,
            reason=request.reason,
        )
    except SalesOrderDocumentNotFound:
        raise _not_found(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/order-intake/{document_id}/create-draft")
async def create_order_draft(document_id: str):
    """Create the reviewed BC draft when write mode is explicitly enabled."""

    try:
        await enrich_and_persist_sales_order_document(_db(), document_id)
        result = await create_draft_order(
            _db(),
            get_bc_service(),
            document_id,
        )
    except SalesOrderDocumentNotFound:
        raise _not_found(document_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    return result
