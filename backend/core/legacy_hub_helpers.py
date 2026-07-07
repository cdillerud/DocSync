"""
Legacy hub helpers: BC/Graph/SharePoint API calls + upload-and-link workflow.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root). No logic changed - only moved so that
routes/*.py modules can import these without a circular import back into
server.py. server.py now imports these names from here instead of defining
them inline.

NOTE (flagged in MIGRATION_PROGRESS.md, not fixed here to keep this a
pure move): services/business_central_service.py has its own, separate
get_bc_token() for the BusinessCentralService class (vendors/POs/invoices/
sales-order creation). This module's get_bc_token()/get_bc_companies()/
get_bc_sales_orders()/link_document_to_bc() are a distinct, older code path
used for the generic document-upload-and-link flow. They are not currently
duplicative in scope, but the credential-fetching logic (get_bc_token) is
duplicated in two places. Worth consolidating later; out of scope for this
no-behavior-change migration.
"""
import uuid
import httpx
from datetime import datetime, timezone

from core.db import db
from core import config

# NOTE: import the config MODULE and read config.X inside each function body
# (not `from core.config import X`). Settings can be hot-reloaded at runtime
# via PUT /api/settings/config (see server.py update_settings_config, which
# writes through to core.config - see MIGRATION_PROGRESS.md). A one-time
# `from core.config import X` would snapshot the value at import time and
# never see those updates - that was a real regression caught while
# migrating this file and fixed here.

FOLDER_MAP = {
    "SalesOrder": "Sales", "SalesInvoice": "Sales",
    "PurchaseInvoice": "Purchase", "PurchaseOrder": "Purchase",
    "Shipment": "Warehouse", "Receipt": "Warehouse",
    "Other": "Incoming"
}

MOCK_COMPANIES = [
    {"id": "c1d2e3f4-0000-0000-0000-000000000001", "name": "GPI Packaging Ltd", "displayName": "GPI Packaging Ltd"},
    {"id": "c1d2e3f4-0000-0000-0000-000000000002", "name": "GPI Test Company", "displayName": "GPI Test Company"}
]

MOCK_SALES_ORDERS = [
    {"id": "a1b2c3d4-1111-0000-0000-000000000001", "number": "SO-1001", "orderDate": "2025-11-15", "customerName": "Acme Corp", "status": "Open", "totalAmountIncludingVAT": 1250.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000002", "number": "SO-1002", "orderDate": "2025-11-16", "customerName": "Widget Co", "status": "Open", "totalAmountIncludingVAT": 3400.50},
    {"id": "a1b2c3d4-1111-0000-0000-000000000003", "number": "SO-1003", "orderDate": "2025-12-01", "customerName": "TechnoServ Ltd", "status": "Released", "totalAmountIncludingVAT": 8900.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000004", "number": "SO-1004", "orderDate": "2025-12-05", "customerName": "PackRight Inc", "status": "Open", "totalAmountIncludingVAT": 520.75},
    {"id": "a1b2c3d4-1111-0000-0000-000000000005", "number": "SO-1005", "orderDate": "2026-01-10", "customerName": "Global Foods Ltd", "status": "Released", "totalAmountIncludingVAT": 12300.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000006", "number": "SO-1006", "orderDate": "2026-01-15", "customerName": "MediPack Solutions", "status": "Open", "totalAmountIncludingVAT": 4560.25},
    {"id": "a1b2c3d4-1111-0000-0000-000000000007", "number": "SO-1007", "orderDate": "2026-02-01", "customerName": "EuroPack GmbH", "status": "Open", "totalAmountIncludingVAT": 7800.00},
]


async def get_graph_token():
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        return "mock-graph-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{config.TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": config.GRAPH_CLIENT_ID, "client_secret": config.GRAPH_CLIENT_SECRET, "scope": "https://graph.microsoft.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Graph token error: {error_desc}")
        return data["access_token"]


async def get_email_token():
    """Get Graph token specifically for email access (Mail.Read)"""
    client_id = config.EMAIL_CLIENT_ID or config.GRAPH_CLIENT_ID
    client_secret = config.EMAIL_CLIENT_SECRET or config.GRAPH_CLIENT_SECRET

    if config.DEMO_MODE or not client_id:
        return "mock-email-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{config.TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret, "scope": "https://graph.microsoft.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Email token error: {error_desc}")
        return data["access_token"]


async def get_bc_token():
    if config.DEMO_MODE or not config.BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{config.TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": config.BC_CLIENT_ID, "client_secret": config.BC_CLIENT_SECRET, "scope": "https://api.businesscentral.dynamics.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]


async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id, "item_id": item_id,
            "web_url": f"https://{config.SHAREPOINT_SITE_HOSTNAME}{config.SHAREPOINT_SITE_PATH}/{config.SHAREPOINT_LIBRARY_NAME}/{folder}/{file_name}",
            "name": file_name
        }
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{config.SHAREPOINT_SITE_HOSTNAME}:{config.SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        site_data = site_resp.json()
        if site_resp.status_code == 401 or site_resp.status_code == 403:
            raise Exception(
                f"Graph API permission denied (HTTP {site_resp.status_code}). "
                f"The app registration needs 'Sites.ReadWrite.All' (Application) permission with admin consent. "
                f"Go to Azure Portal > App Registrations > {config.GRAPH_CLIENT_ID} > API Permissions > Add 'Sites.ReadWrite.All' > Grant admin consent."
            )
        if site_resp.status_code == 404 or "id" not in site_data:
            error = site_data.get("error", {})
            raise Exception(
                f"SharePoint site not found (HTTP {site_resp.status_code}). "
                f"Check config.SHAREPOINT_SITE_HOSTNAME='{config.SHAREPOINT_SITE_HOSTNAME}' and config.SHAREPOINT_SITE_PATH='{config.SHAREPOINT_SITE_PATH}'. "
                f"Detail: {error.get('message', error.get('code', 'unknown'))}"
            )
        if "id" not in site_data:
            raise Exception(f"Unexpected Graph response: {str(site_data)[:200]}")
        site_id = site_data["id"]

        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives_data = drives_resp.json()
        if drives_resp.status_code in (401, 403):
            raise Exception(f"Graph permission denied listing drives (HTTP {drives_resp.status_code}). Ensure 'Sites.ReadWrite.All' permission is granted.")
        if "error" in drives_data:
            raise Exception(f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}")
        drives = drives_data.get("value", [])
        drive = next((d for d in drives if d["name"] == config.SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            raise Exception(f"Document library '{config.SHAREPOINT_LIBRARY_NAME}' not found. Available: {[d['name'] for d in drives]}")
        drive_id = drive["id"]

        upload_resp = await c.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder}/{file_name}:/content",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=file_content)
        item = upload_resp.json()
        if upload_resp.status_code in (401, 403):
            raise Exception(f"Upload permission denied (HTTP {upload_resp.status_code}). Ensure app has 'Files.ReadWrite.All' or 'Sites.ReadWrite.All'.")
        if "id" not in item:
            error = item.get("error", {})
            raise Exception(f"Upload failed (HTTP {upload_resp.status_code}): {error.get('message', error.get('code', item))}")
        return {"drive_id": drive_id, "item_id": item["id"], "web_url": item.get("webUrl", ""), "name": file_name}


async def create_sharing_link(drive_id: str, item_id: str):
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        return f"https://{config.SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/createLink",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "view", "scope": "organization"})
        data = resp.json()
        if "error" in data:
            raise Exception(f"Sharing link error: {data['error'].get('message', data['error'])}")
        return data.get("link", {}).get("webUrl", "")


async def get_bc_companies():
    if config.DEMO_MODE or not config.BC_CLIENT_ID:
        return MOCK_COMPANIES
    token = await get_bc_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies",
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            if "NoEnvironment" in resp.text:
                raise Exception(f"BC environment '{config.BC_ENVIRONMENT}' does not exist. Check the environment name in Settings.")
            raise Exception(f"BC API not found (404): {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise Exception(f"BC permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC companies error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])


async def get_bc_sales_orders(order_no: str = None):
    if config.DEMO_MODE or not config.BC_CLIENT_ID:
        orders = MOCK_SALES_ORDERS
        if order_no:
            orders = [o for o in orders if order_no.lower() in o["number"].lower()]
        return orders
    token = await get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        raise Exception("No BC companies found")
    company_id = companies[0]["id"]
    async with httpx.AsyncClient(timeout=30.0) as c:
        url = f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders"
        if order_no:
            url += f"?$filter=contains(number,'{order_no}')"
        resp = await c.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (401, 403):
            raise Exception(f"BC sales orders permission denied (HTTP {resp.status_code}). Ensure the app has D365 AUTOMATION role in BC.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC sales orders error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])


async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str, file_content: bytes = None, content_type: str = None, bc_entity: str = "salesOrders"):
    """
    Attach a document to a BC record using the documentAttachments API.

    Args:
        bc_record_id: The GUID of the BC record
        share_link: SharePoint sharing link (stored in attachment notes if possible)
        file_name: Name of the file to attach
        file_content: Binary content of the file to upload
        content_type: MIME type of the file (e.g., 'application/pdf')
        bc_entity: The BC entity type (e.g., 'salesOrders', 'purchaseInvoices', 'salesInvoices')

    Returns:
        dict with success status and attachment details
    """
    if config.DEMO_MODE or not config.BC_CLIENT_ID:
        return {"success": True, "method": "mock", "note": f"In production: file will be attached to BC {bc_entity} via documentAttachments API"}

    if not file_content:
        return {"success": False, "method": "api", "error": "No file content provided for attachment"}

    token = await get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        return {"success": False, "method": "api", "error": "No BC companies found"}

    company_id = companies[0]["id"]

    async with httpx.AsyncClient(timeout=60.0) as c:
        attach_url = f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments"

        if not content_type:
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            content_type_map = {
                'pdf': 'application/pdf',
                'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xls': 'application/vnd.ms-excel',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')

        attach_payload = {"attachmentType": "Document", "fileName": file_name}
        attach_resp = await c.post(
            attach_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=attach_payload)
        attach_data = attach_resp.json()
        if attach_resp.status_code in (401, 403):
            return {"success": False, "method": "api", "error": f"Attachment permission denied (HTTP {attach_resp.status_code})"}
        if "id" not in attach_data:
            error = attach_data.get("error", {})
            return {"success": False, "method": "api", "error": f"Attachment metadata failed: {error.get('message', error.get('code', attach_data))}"}

        attachment_id = attach_data["id"]
        content_url = f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments({attachment_id})/documentAttachmentContent"
        content_resp = await c.patch(
            content_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            content=file_content)
        if content_resp.status_code not in (200, 204):
            return {"success": False, "method": "api", "error": f"Attachment content upload failed (HTTP {content_resp.status_code}): {content_resp.text[:200]}", "attachment_id": attachment_id}

        return {"success": True, "method": "api", "attachment_id": attachment_id, "share_link_note": share_link}


async def run_upload_and_link_workflow(doc_id: str, file_content: bytes, file_name: str, doc_type: str, bc_record_id: str = None, bc_document_no: str = None):
    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    doc_type_to_bc_entity = {
        "SalesOrder": "salesOrders",
        "SalesInvoice": "salesInvoices",
        "PurchaseInvoice": "purchaseInvoices",
        "PurchaseOrder": "purchaseOrders"
    }
    bc_entity = doc_type_to_bc_entity.get(doc_type, "salesOrders")

    try:
        folder = FOLDER_MAP.get(doc_type, "Incoming")
        step1_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "upload_to_sharepoint", "status": "running", "started": step1_start})
        sp_result = await upload_to_sharepoint(file_content, file_name, folder)
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"drive_id": sp_result["drive_id"], "item_id": sp_result["item_id"], "folder": folder}

        step2_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "create_sharing_link", "status": "running", "started": step2_start})
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"share_link": share_link}

        bc_linked = False
        bc_error = None
        if bc_record_id or bc_document_no:
            step3_start = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "validate_bc_record", "status": "running", "started": step3_start})
            try:
                orders = await get_bc_sales_orders(order_no=bc_document_no)
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
