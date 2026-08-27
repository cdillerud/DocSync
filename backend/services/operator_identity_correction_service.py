"""Fail-closed identity invalidation for operator match corrections.

A manual vendor/PO correction changes the business identity evidence for a
Document Hub record. Any previously derived BC SystemId/readiness must therefore
be treated as stale until resolution is run again. The prior identity is kept in
append-only audit history so correction never destroys provenance.
"""

from datetime import datetime, timezone


FINAL_LINK_STATES = {"LinkedToBC", "Posted"}


def material_identity_correction(doc: dict, *, vendor_id=None, po_number=None) -> bool:
    """Return True when the operator changed vendor or PO identity evidence."""
    vendor_changed = (
        vendor_id is not None
        and str(vendor_id).strip()
        != str(doc.get("vendor_id") or doc.get("vendor_canonical") or "").strip()
    )
    po_changed = (
        po_number is not None
        and str(po_number).strip()
        != str(
            doc.get("po_number_clean")
            or (doc.get("po_resolution") or {}).get("po_number")
            or ""
        ).strip()
    )
    return vendor_changed or po_changed


def build_identity_invalidation(doc: dict, *, vendor_id=None, po_number=None) -> dict:
    """Build fail-closed fields and an audit snapshot for a material correction.

    Already-final BC linkage is not silently rewritten. That requires an
    explicit unlink/correction workflow so an operator cannot orphan a live BC
    link merely by editing review fields.
    """
    if not material_identity_correction(doc, vendor_id=vendor_id, po_number=po_number):
        return {"changed": False, "set": {}, "audit": None}

    if doc.get("status") in FINAL_LINK_STATES or doc.get("bc_link_created") is True:
        raise ValueError(
            "Document already has final BC linkage; use explicit unlink/recovery before changing vendor or PO"
        )

    now = datetime.now(timezone.utc).isoformat()
    audit = {
        "corrected_at": now,
        "previous_vendor_id": doc.get("vendor_id") or doc.get("vendor_canonical"),
        "previous_po_number": (
            doc.get("po_number_clean")
            or (doc.get("po_resolution") or {}).get("po_number")
        ),
        "previous_bc_record_id": doc.get("bc_record_id"),
        "previous_bc_system_id": doc.get("bc_system_id"),
        "previous_bc_entity_type": doc.get("bc_entity_type"),
        "previous_bc_document_no": doc.get("bc_document_no"),
        "previous_delivery_status": doc.get("delivery_status"),
        "previous_import_ready": bool(doc.get("import_ready")),
        "corrected_vendor_id": vendor_id,
        "corrected_po_number": po_number,
        "source": "ap_review",
    }

    return {
        "changed": True,
        "audit": audit,
        "set": {
            "bc_record_id": None,
            "bc_system_id": None,
            "bc_entity_type": None,
            "bc_document_no": None,
            "po_resolution": None,
            "po_candidates": [],
            "match_method": "manual_correction_pending_resolution",
            "match_score": 0.0,
            "import_ready": False,
            "delivery_status": "NeedsResolution",
            "status": "NeedsReview",
            "workflow_status": "needs_review",
            "square9_stage": "needs_review",
            "sharepoint_parity_metadata_stale": True,
            "identity_correction_pending_resolution": True,
            "identity_corrected_at": now,
        },
    }


async def apply_identity_invalidation(
    db,
    doc: dict,
    *,
    vendor_id=None,
    po_number=None,
) -> dict:
    """Persist invalidation + append-only audit for one Hub document."""
    change = build_identity_invalidation(
        doc,
        vendor_id=vendor_id,
        po_number=po_number,
    )
    if not change["changed"]:
        return change

    await db.hub_documents.update_one(
        {"id": doc["id"]},
        {
            "$set": change["set"],
            "$push": {"identity_correction_history": change["audit"]},
        },
    )
    return change


__all__ = [
    "material_identity_correction",
    "build_identity_invalidation",
    "apply_identity_invalidation",
]
