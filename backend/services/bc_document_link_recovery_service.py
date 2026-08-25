"""Idempotent recovery for SharePoint-success / BC-link-failed documents.

Recovery must never upload the file again. It reuses the existing SharePoint
identity, resolves BC SystemId if needed, checks whether the link already exists,
and only then creates the missing BC link.
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


async def recover_bc_document_link(doc_id: str) -> dict:
    """Repair BC linkage for one already-uploaded Hub document without re-uploading."""
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
                    "bc_link_recovery_attempted_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return {"success": False, "recovered": False, "error": error}
        result = {"success": True, "recovered": True, "already_linked": False}

    recovered_at = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_system_id": system_id,
            "bc_link_created": True,
            "bc_link_error": "",
            "delivery_status": "delivered",
            "import_ready": True,
            "bc_link_recovered_at": recovered_at,
        }},
    )
    result.update({
        "doc_id": doc_id,
        "bc_system_id": system_id,
        "delivery_status": "delivered",
        "import_ready": True,
    })
    return result


__all__ = ["recover_bc_document_link"]
