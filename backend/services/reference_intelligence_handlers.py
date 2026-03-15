"""
GPI Document Hub - Reference Intelligence Domain Handlers

Authoritative implementations of reference-intelligence-domain route handlers,
extracted from server.py during the "Reference Intelligence Handler Extraction"
remediation pass.

These are route-facing orchestration functions consumed by
routers/reference_intelligence.py via add_api_route().

All service getters are sourced from their proper service modules.
No server.py-local functions are required by this module.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Query

from deps import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy service getters (avoid circular imports at module level)
# ---------------------------------------------------------------------------

def _get_reference_resolver():
    from services.bc_reference_resolver import get_reference_resolver
    return get_reference_resolver()


def _get_event_service():
    from services.event_service import get_event_service
    return get_event_service()


def _get_reference_intelligence_service():
    from services.reference_intelligence_service import get_reference_intelligence_service
    return get_reference_intelligence_service()


def _get_auto_resolve_service():
    from services.auto_resolution_service import get_auto_resolve_service
    return get_auto_resolve_service()


def _get_label_correction_service():
    from services.label_correction_service import get_label_correction_service
    return get_label_correction_service()


def _get_vep_service():
    from services.vendor_extraction_profile_service import get_vep_service
    return get_vep_service()


def _get_layout_fingerprint_service():
    from services.layout_fingerprint_service import get_layout_fingerprint_service
    return get_layout_fingerprint_service()


def _get_vendor_intelligence_service():
    from services.vendor_intelligence_service import get_vendor_intelligence_service
    return get_vendor_intelligence_service()


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


async def resolve_bc_reference(
    reference_number: str = Query(..., description="Reference number to resolve"),
    tables: Optional[str] = Query(None, description="Comma-separated tables to check"),
):
    """
    Resolve a reference number against BC tables.

    Checks in order: Purchase Orders, Posted Purchase Invoices,
    Sales Orders, Posted Sales Invoices, Posted Sales Shipments.
    """
    resolver = _get_reference_resolver()

    check_tables = tables.split(",") if tables else None

    result = await resolver.resolve_reference(reference_number, check_tables)

    event_service = _get_event_service()
    if event_service:
        await event_service.emit(
            event_type="reference.resolve.completed",
            document_id="api_call",
            status="completed" if result.status == "found" else "warning",
            source_service="bc_reference_resolver",
            payload=result.to_dict(),
        )

    return result.to_dict()


async def resolve_document_reference(doc_id: str):
    """
    Resolve PO/Order reference for a specific document.

    Looks up extracted PO number or order reference and resolves against BC.
    """
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    reference_number = (
        doc.get("po_number_clean")
        or doc.get("extracted_fields", {}).get("po_number")
        or doc.get("bol_number")
        or doc.get("extracted_fields", {}).get("bol_number")
    )

    if not reference_number:
        return {
            "document_id": doc_id,
            "status": "no_reference",
            "message": "No PO or BOL reference found in document",
        }

    resolver = _get_reference_resolver()
    result = await resolver.resolve_reference(reference_number)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "reference_resolution": result.to_dict(),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }},
    )

    event_service = _get_event_service()
    if event_service:
        await event_service.emit(
            event_type="reference.resolve.completed",
            document_id=doc_id,
            status="completed" if result.status == "found" else "warning",
            source_service="bc_reference_resolver",
            payload=result.to_dict(),
        )

    return {
        "document_id": doc_id,
        **result.to_dict(),
    }


async def resolve_document_intelligence(doc_id: str):
    """
    Full AI-Assisted Reference Intelligence resolution for a document.

    Extracts all candidate references, classifies them, resolves against BC
    with document-type-aware strategy, and scores matches.
    """
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ref_service = _get_reference_intelligence_service()
    if not ref_service:
        raise HTTPException(status_code=503, detail="Reference Intelligence Service not initialized")

    extracted_fields = doc.get("extracted_fields", {})
    if not extracted_fields:
        extracted_fields = {}
    for fld in ["po_number", "bol_number", "invoice_number", "order_number", "shipment_number"]:
        if doc.get(fld) and not extracted_fields.get(fld):
            extracted_fields[fld] = doc[fld]
    if doc.get("po_number_clean") and not extracted_fields.get("po_number"):
        extracted_fields["po_number"] = doc["po_number_clean"]
    if doc.get("invoice_number_clean") and not extracted_fields.get("invoice_number"):
        extracted_fields["invoice_number"] = doc["invoice_number_clean"]

    document_text = doc.get("extracted_text") or doc.get("raw_text") or ""

    resolution = await ref_service.resolve_document_references(
        document=doc,
        extracted_fields=extracted_fields,
        document_text=document_text,
    )

    await ref_service.update_document_references(doc_id, resolution)

    return resolution.to_dict()


async def get_document_reference_intelligence(doc_id: str):
    """
    Get stored reference intelligence data for a document.
    Returns the last resolution result without re-running.
    """
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ref_intel = doc.get("reference_intelligence")
    if not ref_intel:
        return {
            "document_id": doc_id,
            "status": "not_resolved",
            "message": "Reference intelligence has not been run for this document. POST to /resolve-intelligence to trigger.",
        }

    return ref_intel


async def trigger_auto_resolve(doc_id: str):
    """Manually enqueue a document for auto-resolution (re-run)."""
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = _get_auto_resolve_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Auto-resolution service not initialized")

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"reference_intelligence_status": "not_run"}},
    )
    await svc.enqueue(doc_id)

    return {"status": "queued", "document_id": doc_id}


async def get_matching_debug(doc_id: str):
    """
    Get full matching diagnostics for a document.
    Shows: extraction, normalization, resolver strategy, cache/API results,
    candidate scores with breakdown, decision and failure reasons.
    """
    db = get_db()

    diag = await db.matching_diagnostics.find_one(
        {"document_id": doc_id}, {"_id": 0},
    )

    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "reference_intelligence": 1, "reference_candidates": 1,
         "reference_match_outcome": 1, "reference_best_match": 1,
         "document_type": 1, "vendor_canonical": 1, "vendor_raw": 1,
         "unified_vendor_match": 1, "freight_gl_classification": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ref_intel = doc.get("reference_intelligence", {})

    label_corrections = []
    lc_svc = _get_label_correction_service()
    if lc_svc:
        label_corrections = await lc_svc.get_corrections_for_document(doc_id)

    vendor_patterns = None
    vendor_id = doc.get("vendor_canonical") or doc.get("vendor_raw") or ""
    if lc_svc and vendor_id:
        vendor_patterns = await lc_svc.get_vendor_patterns(vendor_id)

    vep_data = None
    vep_svc = _get_vep_service()
    if vep_svc and vendor_id:
        vep_data = await vep_svc.get_resolver_adjustments(vendor_id)
        if not vep_data or not vep_data.get("has_profile"):
            alt_vendor = doc.get("vendor_raw") or doc.get("matched_vendor_name") or ""
            if alt_vendor and alt_vendor != vendor_id:
                vep_data = await vep_svc.get_resolver_adjustments(alt_vendor)

    layout_fp_data = None
    layout_svc = _get_layout_fingerprint_service()
    if layout_svc:
        layout_fp_data = await layout_svc.get_fingerprint_for_document(doc_id)
        if layout_fp_data and layout_fp_data.get("layout_family_id"):
            family_detail = await layout_svc.get_family_detail(layout_fp_data["layout_family_id"])
            if family_detail:
                layout_fp_data["family_detail"] = {
                    "documents_count": family_detail.get("documents_count", 0),
                    "first_seen": family_detail.get("first_seen"),
                    "last_seen": family_detail.get("last_seen"),
                    "performance_metrics": family_detail.get("performance_metrics", {}),
                }

    return {
        "document_id": doc_id,
        "document_type": doc.get("document_type"),
        "vendor": vendor_id,
        "is_freight_carrier": (doc.get("unified_vendor_match") or {}).get("is_freight_carrier", False),
        "match_outcome": doc.get("reference_match_outcome") or ref_intel.get("match_outcome"),
        "diagnostics": diag,
        "reference_intelligence": ref_intel,
        "freight_gl": doc.get("freight_gl_classification"),
        "label_corrections": label_corrections,
        "vendor_correction_patterns": vendor_patterns,
        "vendor_extraction_profile": vep_data,
        "layout_fingerprint": layout_fp_data,
    }


async def rerun_matching_with_diagnostics(doc_id: str):
    """
    Rerun reference resolution with full diagnostics capture.
    """
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = _get_reference_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Reference intelligence not initialized")

    result = await svc.resolve_document_references(
        document=doc,
        extracted_fields=doc.get("extracted_fields"),
        capture_diagnostics=True,
    )

    await svc.update_document_references(doc_id, result)

    lc_svc = _get_label_correction_service()
    if lc_svc and result.best_match:
        try:
            corrections = await lc_svc.detect_and_record(
                document_id=doc_id,
                resolution_result=result.to_dict(),
                document=doc,
            )
            if corrections:
                vendor_intel = _get_vendor_intelligence_service()
                uvm = doc.get("unified_vendor_match") or {}
                vid = uvm.get("bc_vendor_no") or doc.get("vendor_raw") or ""
                if vendor_intel and vid:
                    for c in corrections:
                        try:
                            await vendor_intel.update_label_correction_patterns(vid, c)
                        except Exception:
                            pass
        except Exception:
            pass

    return result.to_dict()
