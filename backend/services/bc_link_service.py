"""
GPI Document Hub - Business Central document attachment linking.

This module is a WRITE boundary. Reads may use the configured BC read
environment, but document attachment creation must always use the split
BC_WRITE_ENVIRONMENT model and the central production-write guard.
"""

import logging
import os
from typing import Dict, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
TENANT_ID = os.environ.get("TENANT_ID") or os.environ.get("BC_TENANT_ID", "")
BC_CLIENT_ID = os.environ.get("BC_CLIENT_ID", "")
BC_READ_ENVIRONMENT = os.environ.get("BC_READ_ENVIRONMENT") or os.environ.get(
    "BC_PROD_ENVIRONMENT", "Production"
)
BC_WRITE_ENVIRONMENT = os.environ.get("BC_WRITE_ENVIRONMENT") or os.environ.get(
    "BC_SANDBOX_ENVIRONMENT", "Sandbox_11_3_2025"
)
BC_SALES_LINK_WRITE_ENABLED = (
    os.environ.get("BC_SALES_LINK_WRITE_ENABLED", "false").lower() == "true"
)
BC_COMPANY_ID = os.environ.get("BC_COMPANY_ID", "").strip()
BC_COMPANY_NAME = os.environ.get("BC_COMPANY_NAME", "").strip()

SALES_ENTITIES = frozenset({
    "salesOrders",
    "salesInvoices",
    "salesCreditMemos",
})


def _write_environment() -> str:
    return str(BC_WRITE_ENVIRONMENT or "").strip()


def _sales_write_allowed(bc_entity: str) -> bool:
    return bc_entity not in SALES_ENTITIES or BC_SALES_LINK_WRITE_ENABLED


def _check_write_boundary(bc_entity: str) -> None:
    """Fail closed before any BC attachment write or network side effect."""
    from services.business_central_service import _check_write_protection

    _check_write_protection("link_document_to_bc")
    if not _sales_write_allowed(bc_entity):
        raise PermissionError(
            "BC Sales attachment writes are disabled. "
            "Set BC_SALES_LINK_WRITE_ENABLED=true only when the Sales lane is explicitly activated."
        )


async def _get_bc_token():
    from services.config_service import get_bc_token
    return await get_bc_token()


async def _resolve_company_id(token: str, environment: str) -> str:
    """Resolve the company in the same environment that will receive the write."""
    if BC_COMPANY_ID:
        return BC_COMPANY_ID

    if not TENANT_ID:
        raise RuntimeError("BC tenant is not configured")

    url = (
        "https://api.businesscentral.dynamics.com/v2.0/"
        f"{TENANT_ID}/{environment}/api/v2.0/companies?$top=100"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )

    if response.status_code in (401, 403):
        raise PermissionError(
            f"BC company lookup permission denied (HTTP {response.status_code})"
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"BC company lookup failed (HTTP {response.status_code}): {response.text[:500]}"
        )

    data = response.json()
    companies = data.get("value", [])
    if BC_COMPANY_NAME:
        wanted = BC_COMPANY_NAME.casefold()
        matched = next(
            (
                company
                for company in companies
                if str(company.get("name") or "").casefold() == wanted
                or str(company.get("displayName") or "").casefold() == wanted
            ),
            None,
        )
        if not matched:
            raise RuntimeError(
                f"Configured BC company {BC_COMPANY_NAME!r} was not found in {environment}"
            )
        return str(matched["id"])

    if not companies:
        raise RuntimeError(f"No BC companies found in {environment}")
    if len(companies) > 1:
        raise RuntimeError(
            "Multiple BC companies are available but BC_COMPANY_ID/BC_COMPANY_NAME is not configured; "
            "refusing to guess the write target."
        )
    return str(companies[0]["id"])


def _content_type_for(file_name: str, supplied: Optional[str]) -> str:
    if supplied:
        return supplied
    extension = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "txt": "text/plain",
    }.get(extension, "application/octet-stream")


async def link_document_to_bc(
    bc_record_id: str,
    share_link: str,
    file_name: str,
    file_content: bytes = None,
    content_type: str = None,
    bc_entity: str = "salesOrders",
) -> Dict[str, object]:
    """Attach a document to a BC record using the guarded WRITE environment."""
    _check_write_boundary(bc_entity)

    if DEMO_MODE or not BC_CLIENT_ID:
        return {
            "success": True,
            "method": "mock",
            "target_environment": _write_environment(),
            "note": f"Mock attachment to BC {bc_entity}; no BC write was performed",
        }

    if not file_content:
        return {
            "success": False,
            "method": "api",
            "error": "No file content provided for attachment",
        }
    if not bc_record_id:
        return {
            "success": False,
            "method": "api",
            "error": "No BC record SystemId provided for attachment",
        }

    environment = _write_environment()
    if not environment:
        raise RuntimeError("BC_WRITE_ENVIRONMENT is not configured")

    token = await _get_bc_token()
    company_id = await _resolve_company_id(token, environment)
    resolved_content_type = _content_type_for(file_name, content_type)
    base_url = (
        "https://api.businesscentral.dynamics.com/v2.0/"
        f"{TENANT_ID}/{environment}/api/v2.0/companies({company_id})/"
        f"{bc_entity}({bc_record_id})/documentAttachments"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        create_response = await client.post(
            base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"fileName": file_name},
        )

        if create_response.status_code in (401, 403):
            return {
                "success": False,
                "method": "api",
                "error": (
                    f"BC permission denied (HTTP {create_response.status_code}) "
                    f"creating attachment in {environment}"
                ),
            }
        if create_response.status_code not in (200, 201):
            try:
                error_data = create_response.json()
                error_message = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_message = create_response.text[:500]
            return {
                "success": False,
                "method": "api",
                "error": (
                    f"Failed to create attachment record (HTTP {create_response.status_code}): "
                    f"{error_message}"
                ),
            }

        attachment_data = create_response.json()
        attachment_id = attachment_data.get("id")
        if not attachment_id:
            return {
                "success": False,
                "method": "api",
                "error": f"No attachment ID returned from BC: {attachment_data}",
            }

        content_url = f"{base_url}({attachment_id})/attachmentContent"
        upload_response = await client.patch(
            content_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": resolved_content_type,
                "If-Match": "*",
            },
            content=file_content,
        )

        if upload_response.status_code not in (200, 204):
            try:
                error_data = upload_response.json()
                error_message = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_message = upload_response.text[:500]
            return {
                "success": False,
                "method": "api",
                "attachment_id": attachment_id,
                "error": (
                    f"Failed to upload attachment content (HTTP {upload_response.status_code}): "
                    f"{error_message}"
                ),
            }

    logger.info(
        "Attached document %r to BC %s %s in %s",
        file_name,
        bc_entity,
        bc_record_id,
        environment,
    )
    return {
        "success": True,
        "method": "api",
        "attachment_id": attachment_id,
        "file_name": file_name,
        "bc_entity": bc_entity,
        "bc_record_id": bc_record_id,
        "target_environment": environment,
        "sharepoint_link": share_link,
    }
