"""Idempotent recovery for SharePoint-success / BC-link-failed documents.

Recovery must never upload the file again. It reuses the existing SharePoint
identity, resolves BC SystemId if needed, checks whether the link already exists,
creates only the missing BC link, and then patches parity metadata on the same
SharePoint item before declaring the document delivered/import-ready.
"""

from datetime import datetime, timezone

import httpx

from deps import get_db
from services.bc_document_identity_service import resolve_bc_document_system_id
from services.document_link_visibility_service import (
    build_bc_document_link_filter,
    canonical_document_type,
)
from services.gpi_integration_service import (
    BC_TENANT_ID,
    BC_WRITE_ENVIRONMENT,
    GPI_API_BASE,
    HAS_CREDENTIALS,
    REQUEST_TIMEOUT,
    _get_company_id_standard_api,
    _get_token,
    create_gpi_document_link,
)


async def _find_existing_link(bc_entity: str, bc_document_no: str, doc: dict) -> dict | None:
    """Return an existing BC documentLink for the same SharePoint item/URL."""
    if not HAS_CREDENTIALS:
        return None

    token = await _get_token()
    company_id = await _get_company_id_standard_api(environment=BC_WRITE_ENVIRONMENT)
    url = (
        f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/"
        f"gpi/documents/v1.0/companies({company_id})/documentLinks"
    )
    params = {"$filter": build_bc_document_link_filter(bc_entity, bc_document_no)}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
        )
        resp.raise_for_status()
        links = resp.json().get("value", [])

    target_item = str(doc.get("sharepoint_item_id") or "").strip()
    target_url = str(
        doc.get("sharepoint_web_url") or doc.get("sharepoint_share_link_url") or ""
    ).strip()
    for link in links:
        if target_item and str(link.get("sharePointItemId") or "").strip() == target_item:
            return link
        if target_url and str(link.get("sharePointUrl") or "").strip() == target_url:
            return link
    return None


async def _finalize_existing_item_metadata(doc_id: str, db, doc: dict, system_id: str) -> dict:
    """Patch readiness metadata on the existing SharePoint item only.

    BC Drop records have a stricter lifecycle-aware metadata contract; other
    document families use the generic existing-item parity resync boundary.
    Neither path uploads bytes or creates a replacement SharePoint item.
    """
    source = str(doc.get("source") or "").strip().lower()
    if source == "bc_drop" or doc.get("bc_source_table_id") or doc.get("bc_source_document_type"):
        from services.bc_drop_parity_metadata_service import write_bc_drop_parity_metadata

        ready_doc = dict(doc)
        ready_doc["bc_system_id"] = system_id
        ready_doc["bc_record_id"] = system_id
        metadata = await write_bc_drop_parity_metadata(ready_doc, ready=True)
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "sharepoint_parity_metadata": metadata,
                "sharepoint_metadata_written_at": now,
                "sharepoint_metadata_resynced_at": now,
                "sharepoint_metadata_error": None,
            }},
        )
        return metadata

    from services.sharepoint_parity_resync_service import resync_existing_sharepoint_parity_metadata

    identity_update = {
        "GPI_SourceSystemId": system_id,
        "GPI_Status": "ImportReady",
        "ImportReady": True,
        "import_ready": True,
        "delivery_status": "ImportReady",
    }
    result = await resync_existing_sharepoint_parity_metadata(
        doc_id,
        db,
        identity_update=identity_update,
    )
    return result["metadata"]


async def recover_bc_document_link(doc_id: str) -> dict:
    """Repair BC linkage and parity metadata without re-uploading file bytes."""
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise LookupError(f"Document {doc_id!r} not found")

    bc_entity = str(doc.get("bc_entity_type") or doc.get("bc_entity") or "").strip()
    bc_document_no = str(doc.get("bc_document_no") or "").strip()
    sharepoint_url = str(
        doc.get("sharepoint_web_url") or doc.get("sharepoint_share_link_url") or ""
    ).strip()
    if not bc_entity or not bc_document_no:
        raise ValueError("BC entity and document number are required for link recovery")
    if not sharepoint_url:
        raise ValueError("Existing SharePoint URL is required for link recovery")
    if not str(doc.get("sharepoint_drive_id") or "").strip() or not str(doc.get("sharepoint_item_id") or "").strip():
        raise ValueError("Existing SharePoint drive/item identity is required for link recovery")

    system_id = str(doc.get("bc_system_id") or doc.get("bc_record_id") or "").strip()
    if not system_id:
        identity = await resolve_bc_document_system_id(bc_entity, bc_document_no)
        system_id = identity["bc_system_id"]

    existing = await _find_existing_link(bc_entity, bc_document_no, doc)
    if existing:
        result = {"success": True, "recovered": True, "already_linked": True}
    else:
        link_result = await create_gpi_document_link(
            bc_system_id=system_id,
            bc_document_no=bc_document_no,
            document_type=canonical_document_type(bc_entity),
            sharepoint_url=sharepoint_url,
            sharepoint_drive_id=str(doc.get("sharepoint_drive_id") or ""),
            sharepoint_item_id=str(doc.get("sharepoint_item_id") or ""),
            uploaded_by=str(doc.get("uploaded_by") or "GPI Hub Recovery"),
            source="GPIHub",
        )
        if not link_result.get("success"):
            error = link_result.get("error", "BC document link recovery failed")
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_system_id": system_id,
                    "bc_link_created": False,
                    "bc_link_error": error,
                    "delivery_status": "bc_link_failed",
                    "import_ready": False,
                    "ImportReady": False,
                    "bc_link_recovery_attempted_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return {"success": False, "recovered": False, "error": error}
        result = {"success": True, "recovered": True, "already_linked": False}

    try:
        metadata = await _finalize_existing_item_metadata(doc_id, db, doc, system_id)
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_system_id": system_id,
                "bc_record_id": system_id,
                "bc_link_created": True,
                "bc_link_error": "",
                "delivery_status": "bc_link_recovered_metadata_failed",
                "import_ready": False,
                "ImportReady": False,
                "sharepoint_metadata_error": str(exc),
                "bc_link_recovery_attempted_at": now,
            }},
        )
        return {
            "success": False,
            "recovered": False,
            "bc_link_recovered": True,
            "metadata_recovered": False,
            "doc_id": doc_id,
            "bc_system_id": system_id,
            "delivery_status": "bc_link_recovered_metadata_failed",
            "error": str(exc),
        }

    recovered_at = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_system_id": system_id,
            "bc_record_id": system_id,
            "bc_link_created": True,
            "bc_link_error": "",
            "delivery_status": "ImportReady",
            "import_ready": True,
            "ImportReady": True,
            "sharepoint_metadata_error": None,
            "bc_link_recovered_at": recovered_at,
        }},
    )
    result.update({
        "doc_id": doc_id,
        "bc_system_id": system_id,
        "delivery_status": "ImportReady",
        "import_ready": True,
        "metadata_recovered": True,
        "metadata": metadata,
    })
    return result


__all__ = ["recover_bc_document_link"]
