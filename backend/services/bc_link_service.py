"""
GPI Document Hub - BC Link Service

Extracted from server.py — authoritative implementation of BC document attachment:
  - link_document_to_bc: Attach a document to a BC record via documentAttachments API

Falls back to mock behavior in DEMO_MODE or when BC_CLIENT_ID is not configured.
"""

import os
import logging
import httpx

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── BC Config ──
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')


async def _get_bc_token():
    from services.config_service import get_bc_token
    return await get_bc_token()


async def _get_bc_companies():
    from services.bc_api_helpers import get_bc_companies
    return await get_bc_companies()


async def link_document_to_bc(
    bc_record_id: str,
    share_link: str,
    file_name: str,
    file_content: bytes = None,
    content_type: str = None,
    bc_entity: str = "salesOrders",
):
    """
    Attach a document to a BC record using the documentAttachments API.

    Args:
        bc_record_id: The GUID of the BC record
        share_link: SharePoint sharing link (stored in attachment notes if possible)
        file_name: Name of the file to attach
        file_content: Binary content of the file to upload
        content_type: MIME type of the file
        bc_entity: The BC entity type (e.g., 'salesOrders', 'purchaseInvoices')

    Returns:
        dict with success status and attachment details
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"success": True, "method": "mock", "note": f"In production: file will be attached to BC {bc_entity} via documentAttachments API"}

    if not file_content:
        return {"success": False, "method": "api", "error": "No file content provided for attachment"}

    token = await _get_bc_token()
    companies = await _get_bc_companies()
    if not companies:
        return {"success": False, "method": "api", "error": "No BC companies found"}

    company_id = companies[0]["id"]

    async with httpx.AsyncClient(timeout=60.0) as c:
        attach_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments"

        if not content_type:
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            content_type_map = {
                'pdf': 'application/pdf',
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'gif': 'image/gif',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xls': 'application/vnd.ms-excel',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'txt': 'text/plain',
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')

        attachment_payload = {"fileName": file_name}

        create_resp = await c.post(
            attach_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=attachment_payload
        )

        if create_resp.status_code in (401, 403):
            return {
                "success": False, "method": "api",
                "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC."
            }

        if create_resp.status_code not in (200, 201):
            try:
                error_data = create_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = create_resp.text[:500]
            return {
                "success": False, "method": "api",
                "error": f"Failed to create attachment record (HTTP {create_resp.status_code}): {error_msg}"
            }

        attachment_data = create_resp.json()
        attachment_id = attachment_data.get("id")

        if not attachment_id:
            return {
                "success": False, "method": "api",
                "error": f"No attachment ID returned from BC: {attachment_data}"
            }

        content_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"

        upload_resp = await c.patch(
            content_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "If-Match": "*"
            },
            content=file_content
        )

        if upload_resp.status_code not in (200, 204):
            try:
                error_data = upload_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = upload_resp.text[:500]
            return {
                "success": False, "method": "api",
                "error": f"Failed to upload attachment content (HTTP {upload_resp.status_code}): {error_msg}"
            }

        logger.info("Successfully attached document '%s' to BC %s %s", file_name, bc_entity, bc_record_id)

        return {
            "success": True,
            "method": "api",
            "attachment_id": attachment_id,
            "file_name": file_name,
            "bc_entity": bc_entity,
            "note": f"Document attached to {bc_entity} in BC. SharePoint link: {share_link}"
        }
