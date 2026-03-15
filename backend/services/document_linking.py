"""
GPI Document Hub - Document Linking Service

Link documents to Business Central records via the documentAttachments API.
Upload-and-link workflow orchestration for SharePoint + BC.
Extracted from server.py during Architecture Hardening and Final Orchestration passes.

Dependencies:
  - deps: config vars, get_db(), UPLOAD_DIR, FOLDER_MAP
  - services.bc_api_helpers: get_bc_companies, get_bc_sales_orders
  - services.sharepoint_helpers: upload_to_sharepoint, create_sharing_link
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException

import deps

logger = logging.getLogger(__name__)


async def _get_bc_token():
    """Acquire BC API token."""
    if deps.DEMO_MODE or not deps.BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{deps.TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": deps.BC_CLIENT_ID,
                "client_secret": deps.BC_CLIENT_SECRET,
                "scope": "https://api.businesscentral.dynamics.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]


async def _get_bc_companies():
    from services.bc_api_helpers import get_bc_companies
    return await get_bc_companies()


async def _get_bc_sales_orders(order_no=None):
    from services.bc_api_helpers import get_bc_sales_orders
    return await get_bc_sales_orders(order_no=order_no)


async def link_document_to_bc(
    bc_record_id: str,
    share_link: str,
    file_name: str,
    file_content: bytes = None,
    content_type: str = None,
    bc_entity: str = "salesOrders",
) -> dict:
    """Attach a document to a BC record using the documentAttachments API."""
    if deps.DEMO_MODE or not deps.BC_CLIENT_ID:
        return {
            "success": True,
            "method": "mock",
            "note": f"In production: file will be attached to BC {bc_entity} via documentAttachments API",
        }

    if not file_content:
        return {"success": False, "method": "api", "error": "No file content provided for attachment"}

    token = await _get_bc_token()
    companies = await _get_bc_companies()
    if not companies:
        return {"success": False, "method": "api", "error": "No BC companies found"}

    company_id = companies[0]["id"]

    async with httpx.AsyncClient(timeout=60.0) as c:
        attach_url = (
            f"https://api.businesscentral.dynamics.com/v2.0/{deps.TENANT_ID}/{deps.BC_ENVIRONMENT}"
            f"/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments"
        )

        if not content_type:
            ext = file_name.lower().split(".")[-1] if "." in file_name else ""
            content_type_map = {
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
            }
            content_type = content_type_map.get(ext, "application/octet-stream")

        attachment_payload = {"fileName": file_name}

        create_resp = await c.post(
            attach_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=attachment_payload,
        )

        if create_resp.status_code in (401, 403):
            return {
                "success": False,
                "method": "api",
                "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC.",
            }

        if create_resp.status_code not in (200, 201):
            try:
                error_data = create_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = create_resp.text[:500]
            return {
                "success": False,
                "method": "api",
                "error": f"Failed to create attachment record (HTTP {create_resp.status_code}): {error_msg}",
            }

        attachment_data = create_resp.json()
        attachment_id = attachment_data.get("id")

        if not attachment_id:
            return {
                "success": False,
                "method": "api",
                "error": f"No attachment ID returned from BC: {attachment_data}",
            }

        content_url = (
            f"https://api.businesscentral.dynamics.com/v2.0/{deps.TENANT_ID}/{deps.BC_ENVIRONMENT}"
            f"/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})"
            f"/documentAttachments({attachment_id})/attachmentContent"
        )

        upload_resp = await c.patch(
            content_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "If-Match": "*",
            },
            content=file_content,
        )

        if upload_resp.status_code not in (200, 204):
            try:
                error_data = upload_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = upload_resp.text[:500]
            return {
                "success": False,
                "method": "api",
                "error": f"Failed to upload attachment content (HTTP {upload_resp.status_code}): {error_msg}",
            }

        logger.info("Successfully attached document '%s' to BC %s %s", file_name, bc_entity, bc_record_id)

        return {
            "success": True,
            "method": "api",
            "attachment_id": attachment_id,
            "file_name": file_name,
            "bc_entity": bc_entity,
            "note": f"Document attached to {bc_entity} in BC. SharePoint link: {share_link}",
        }


async def link_document(doc_id: str) -> dict:
    """
    Full link-to-BC workflow: validate BC record, attach document, update status.
    """
    db = deps.get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.get("sharepoint_share_link_url"):
        raise HTTPException(status_code=400, detail="Document has no SharePoint link yet")
    bc_record_id = doc.get("bc_record_id")
    bc_document_no = doc.get("bc_document_no")
    if not bc_record_id and not bc_document_no:
        raise HTTPException(status_code=400, detail="No BC record reference set on this document")

    # Load the stored file for attachment
    upload_dir = Path(deps.UPLOAD_DIR)
    file_path = upload_dir / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()

    # Determine BC entity from document type or job_type
    doc_type = doc.get("document_type", "Other")
    job_type = doc.get("suggested_job_type", "")

    job_config = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if job_config:
        bc_entity = job_config.get("bc_entity", "salesOrders")
    else:
        doc_type_to_bc_entity = {
            "SalesOrder": "salesOrders",
            "SalesInvoice": "salesInvoices",
            "PurchaseInvoice": "purchaseInvoices",
            "PurchaseOrder": "purchaseOrders",
            "AP_Invoice": "purchaseInvoices",
        }
        bc_entity = doc_type_to_bc_entity.get(doc_type, doc_type_to_bc_entity.get(job_type, "salesOrders"))

    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    try:
        steps.append({"step": "validate_bc_record", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
        orders = await _get_bc_sales_orders(order_no=bc_document_no)
        if orders:
            steps[-1]["status"] = "completed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "link_to_bc", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id or orders[0]["id"],
                share_link=doc["sharepoint_share_link_url"],
                file_name=doc["file_name"],
                file_content=file_content,
                bc_entity=bc_entity,
            )
            if link_result.get("success"):
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = link_result
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"status": "LinkedToBC", "updated_utc": datetime.now(timezone.utc).isoformat(), "last_error": None}},
                )
                wf_status = "Completed"
            else:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = link_result.get("error", "Unknown error")
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"status": "Exception", "last_error": link_result.get("error"), "updated_utc": datetime.now(timezone.utc).isoformat()}},
                )
                wf_status = "Failed"
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {"status": "Exception", "last_error": "BC record not found", "updated_utc": datetime.now(timezone.utc).isoformat()}},
            )
            wf_status = "Failed"

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": wf_status, "steps": steps, "correlation_id": correlation_id,
            "error": None if wf_status == "Completed" else steps[-1].get("error", "BC record not found"),
        }
        await db.hub_workflow_runs.insert_one(workflow)
    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e)})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e),
        }
        await db.hub_workflow_runs.insert_one(workflow)

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})


async def run_upload_and_link_workflow(
    doc_id: str, file_content: bytes, file_name: str, doc_type: str,
    bc_record_id: str = None, bc_document_no: str = None
):
    """
    Upload a document to SharePoint and optionally link it to a BC record.

    Steps:
      1. Upload to SharePoint (using doc_type-based folder)
      2. Create a sharing link
      3. Validate BC record and attach document (if bc_record_id/bc_document_no provided)
      4. Update document status and create workflow audit trail

    Returns:
      (workflow_id, final_status) tuple
    """
    from services.sharepoint_helpers import upload_to_sharepoint, create_sharing_link

    db = deps.get_db()
    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    # Determine BC entity from document type
    doc_type_to_bc_entity = {
        "SalesOrder": "salesOrders",
        "SalesInvoice": "salesInvoices",
        "PurchaseInvoice": "purchaseInvoices",
        "PurchaseOrder": "purchaseOrders"
    }
    bc_entity = doc_type_to_bc_entity.get(doc_type, "salesOrders")

    try:
        # Step 1: Upload to SharePoint
        folder = deps.FOLDER_MAP.get(doc_type, "Incoming")
        step1_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "upload_to_sharepoint", "status": "running", "started": step1_start})
        sp_result = await upload_to_sharepoint(file_content, file_name, folder)
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"drive_id": sp_result["drive_id"], "item_id": sp_result["item_id"], "folder": folder}

        # Step 2: Create sharing link
        step2_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "create_sharing_link", "status": "running", "started": step2_start})
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"share_link": share_link}

        # Step 3: Validate and link BC record
        bc_linked = False
        bc_error = None
        if bc_record_id or bc_document_no:
            step3_start = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "validate_bc_record", "status": "running", "started": step3_start})
            try:
                orders = await _get_bc_sales_orders(order_no=bc_document_no)
                if orders:
                    steps[-1]["status"] = "completed"
                    steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                    steps[-1]["result"] = {"found": True, "order_number": orders[0]["number"], "customer": orders[0]["customerName"]}

                    step4_start = datetime.now(timezone.utc).isoformat()
                    steps.append({"step": "link_to_bc", "status": "running", "started": step4_start})
                    link_result = await link_document_to_bc(
                        bc_record_id=bc_record_id or orders[0]["id"],
                        share_link=share_link,
                        file_name=file_name,
                        file_content=file_content,
                        bc_entity=bc_entity
                    )
                    if link_result.get("success"):
                        steps[-1]["status"] = "completed"
                        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                        steps[-1]["result"] = link_result
                        bc_linked = True
                    else:
                        steps[-1]["status"] = "failed"
                        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                        steps[-1]["error"] = link_result.get("error", "Unknown error attaching to BC")
                        bc_error = link_result.get("error", "Unknown error attaching to BC")
                else:
                    steps[-1]["status"] = "warning"
                    steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                    steps[-1]["result"] = {"found": False, "note": "BC record not found"}
                    bc_error = "BC record not found"
            except Exception as bc_exc:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = str(bc_exc)
                bc_error = str(bc_exc)

        # Determine final status — SharePoint success is preserved even if BC fails
        if bc_record_id or bc_document_no:
            new_status = "LinkedToBC" if bc_linked else "Classified"
        else:
            new_status = "Classified"

        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "sharepoint_drive_id": sp_result["drive_id"],
            "sharepoint_item_id": sp_result["item_id"],
            "sharepoint_web_url": sp_result["web_url"],
            "sharepoint_share_link_url": share_link,
            "status": new_status,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "last_error": bc_error
        }})

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "upload_and_link",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Completed" if bc_linked else ("CompletedWithWarnings" if not bc_error else "PartialSuccess"),
            "steps": steps, "correlation_id": correlation_id,
            "error": bc_error
        }
        await db.hub_workflow_runs.insert_one(workflow)
        return workflow_id, new_status

    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e), "ended": datetime.now(timezone.utc).isoformat()})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "upload_and_link",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e)
        }
        await db.hub_workflow_runs.insert_one(workflow)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "Exception", "last_error": str(e), "updated_utc": datetime.now(timezone.utc).isoformat()
        }})
        return workflow_id, "Exception"

    return {"document": doc, "workflow_id": workflow_id}
