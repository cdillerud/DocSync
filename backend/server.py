from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Query, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import hashlib
import base64
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Config
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
JWT_SECRET = os.environ.get('JWT_SECRET', 'gpi-hub-secret-key')
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET', '')
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME', 'gamerpackaging.sharepoint.com')
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH', '/sites/GPI-DocumentHub-Test')
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Documents')

app = FastAPI(title="GPI Document Hub API")
api_router = APIRouter(prefix="/api")

# ==================== AUTH ====================
import jwt as pyjwt

TEST_USER = {"username": "admin", "password": "admin", "display_name": "Hub Admin", "role": "administrator"}

class LoginRequest(BaseModel):
    username: str
    password: str

class DocumentUpdate(BaseModel):
    document_type: Optional[str] = None
    bc_record_type: Optional[str] = None
    bc_record_id: Optional[str] = None
    bc_document_no: Optional[str] = None

def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc).timestamp() + 86400}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

@api_router.post("/auth/login")
async def login(req: LoginRequest):
    if req.username == TEST_USER["username"] and req.password == TEST_USER["password"]:
        token = create_token(req.username)
        return {"token": token, "user": {"username": TEST_USER["username"], "display_name": TEST_USER["display_name"], "role": TEST_USER["role"]}}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@api_router.get("/auth/me")
async def get_me():
    return {"username": TEST_USER["username"], "display_name": TEST_USER["display_name"], "role": TEST_USER["role"]}

# ==================== MICROSOFT SERVICES (MOCK/REAL) ====================

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
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return "mock-graph-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": GRAPH_CLIENT_ID, "client_secret": GRAPH_CLIENT_SECRET, "scope": "https://graph.microsoft.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Graph token error: {error_desc}")
        return data["access_token"]

async def get_bc_token():
    if DEMO_MODE or not BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": BC_CLIENT_ID, "client_secret": BC_CLIENT_SECRET, "scope": "https://api.businesscentral.dynamics.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]

async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id, "item_id": item_id,
            "web_url": f"https://{SHAREPOINT_SITE_HOSTNAME}{SHAREPOINT_SITE_PATH}/{SHAREPOINT_LIBRARY_NAME}/{folder}/{file_name}",
            "name": file_name
        }
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Step 1: Resolve site
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}",
            headers={"Authorization": f"Bearer {token}"})
        site_data = site_resp.json()
        if site_resp.status_code == 401 or site_resp.status_code == 403:
            raise Exception(
                f"Graph API permission denied (HTTP {site_resp.status_code}). "
                f"The app registration needs 'Sites.ReadWrite.All' (Application) permission with admin consent. "
                f"Go to Azure Portal > App Registrations > {GRAPH_CLIENT_ID} > API Permissions > Add 'Sites.ReadWrite.All' > Grant admin consent."
            )
        if site_resp.status_code == 404 or "id" not in site_data:
            error = site_data.get("error", {})
            raise Exception(
                f"SharePoint site not found (HTTP {site_resp.status_code}). "
                f"Check SHAREPOINT_SITE_HOSTNAME='{SHAREPOINT_SITE_HOSTNAME}' and SHAREPOINT_SITE_PATH='{SHAREPOINT_SITE_PATH}'. "
                f"Detail: {error.get('message', error.get('code', 'unknown'))}"
            )
        if "id" not in site_data:
            raise Exception(f"Unexpected Graph response: {str(site_data)[:200]}")
        site_id = site_data["id"]

        # Step 2: Resolve drive
        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives_data = drives_resp.json()
        if drives_resp.status_code in (401, 403):
            raise Exception(f"Graph permission denied listing drives (HTTP {drives_resp.status_code}). Ensure 'Sites.ReadWrite.All' permission is granted.")
        if "error" in drives_data:
            raise Exception(f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}")
        drives = drives_data.get("value", [])
        drive = next((d for d in drives if d["name"] == SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            raise Exception(f"Document library '{SHAREPOINT_LIBRARY_NAME}' not found. Available: {[d['name'] for d in drives]}")
        drive_id = drive["id"]

        # Step 3: Upload file
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
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return f"https://{SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
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
    if DEMO_MODE or not BC_CLIENT_ID:
        return MOCK_COMPANIES
    token = await get_bc_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies",
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            # BC returns XML for missing environments
            if "NoEnvironment" in resp.text:
                raise Exception(f"BC environment '{BC_ENVIRONMENT}' does not exist. Check the environment name in Settings.")
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
    if DEMO_MODE or not BC_CLIENT_ID:
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
        url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders"
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

async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str, file_content: bytes = None, content_type: str = None):
    """
    Attach a document to a BC Sales Order using the documentAttachments API.
    
    Args:
        bc_record_id: The GUID of the Sales Order in BC
        share_link: SharePoint sharing link (stored in attachment notes if possible)
        file_name: Name of the file to attach
        file_content: Binary content of the file to upload
        content_type: MIME type of the file (e.g., 'application/pdf')
    
    Returns:
        dict with success status and attachment details
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"success": True, "method": "mock", "note": "In production: file will be attached to BC Sales Order via documentAttachments API"}
    
    if not file_content:
        return {"success": False, "method": "api", "error": "No file content provided for attachment"}
    
    token = await get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        return {"success": False, "method": "api", "error": "No BC companies found"}
    
    company_id = companies[0]["id"]
    
    async with httpx.AsyncClient(timeout=60.0) as c:
        # Step 1: Create the attachment metadata record
        # Using documentAttachments entity bound to salesOrders
        attach_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders({bc_record_id})/documentAttachments"
        
        # Determine content type
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
        
        # Create attachment metadata
        attachment_payload = {
            "fileName": file_name
        }
        
        create_resp = await c.post(
            attach_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=attachment_payload
        )
        
        if create_resp.status_code == 401 or create_resp.status_code == 403:
            return {
                "success": False, 
                "method": "api", 
                "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC."
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
                "error": f"Failed to create attachment record (HTTP {create_resp.status_code}): {error_msg}"
            }
        
        attachment_data = create_resp.json()
        attachment_id = attachment_data.get("id")
        
        if not attachment_id:
            return {
                "success": False,
                "method": "api",
                "error": f"No attachment ID returned from BC: {attachment_data}"
            }
        
        # Step 2: Upload the actual file content using PATCH with attachmentContent
        content_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"
        
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
                "success": False,
                "method": "api",
                "error": f"Failed to upload attachment content (HTTP {upload_resp.status_code}): {error_msg}"
            }
        
        logger.info("Successfully attached document '%s' to BC Sales Order %s", file_name, bc_record_id)
        
        return {
            "success": True,
            "method": "api",
            "attachment_id": attachment_id,
            "file_name": file_name,
            "note": f"Document attached to Sales Order in BC. SharePoint link: {share_link}"
        }

# ==================== WORKFLOW ENGINE ====================

async def run_upload_and_link_workflow(doc_id: str, file_content: bytes, file_name: str, doc_type: str, bc_record_id: str = None, bc_document_no: str = None):
    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    try:
        # Step 1: Upload to SharePoint
        folder = FOLDER_MAP.get(doc_type, "Incoming")
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
                        file_content=file_content
                    )
                    # Check if BC attachment succeeded
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

# ==================== DOCUMENT ENDPOINTS ====================

# Upload storage path
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

@api_router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("Other"),
    bc_record_id: str = Form(None),
    bc_document_no: str = Form(None),
    bc_company_id: str = Form(None),
    source: str = Form("manual_upload")
):
    file_content = await file.read()
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Persist file to disk for potential resubmit
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    doc = {
        "id": doc_id, "source": source, "file_name": file.filename,
        "sha256_hash": sha256_hash, "file_size": len(file_content),
        "content_type": file.content_type,
        "sharepoint_drive_id": None, "sharepoint_item_id": None,
        "sharepoint_web_url": None, "sharepoint_share_link_url": None,
        "document_type": document_type,
        "bc_record_type": "SalesOrder" if document_type == "SalesOrder" else None,
        "bc_company_id": bc_company_id, "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        "status": "Received", "created_utc": now, "updated_utc": now, "last_error": None
    }
    await db.hub_documents.insert_one(doc)

    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, file.filename, document_type, bc_record_id, bc_document_no
    )
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}

@api_router.get("/documents")
async def list_documents(
    status: str = Query(None), document_type: str = Query(None),
    search: str = Query(None), skip: int = Query(0), limit: int = Query(50)
):
    fq = {}
    if status:
        fq["status"] = status
    if document_type:
        fq["document_type"] = document_type
    if search:
        fq["file_name"] = {"$regex": search, "$options": "i"}
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total}

@api_router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    workflows = await db.hub_workflow_runs.find({"document_id": doc_id}, {"_id": 0}).sort("started_utc", -1).to_list(100)
    return {"document": doc, "workflows": workflows}

@api_router.put("/documents/{doc_id}")
async def update_document(doc_id: str, update: DocumentUpdate):
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    result = await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return doc

@api_router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document, its workflows, and stored file."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.hub_documents.delete_one({"id": doc_id})
    await db.hub_workflow_runs.delete_many({"document_id": doc_id})
    file_path = UPLOAD_DIR / doc_id
    if file_path.exists():
        file_path.unlink()
    return {"message": "Document deleted", "id": doc_id}



@api_router.post("/documents/{doc_id}/resubmit")
async def resubmit_document(doc_id: str):
    """Re-submit a failed document: re-run the full workflow using the stored file."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Read stored file from disk
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found on server. Please upload again via the Upload page.")
    file_content = file_path.read_bytes()
    now = datetime.now(timezone.utc).isoformat()

    # Reset document status
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "status": "Received",
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "last_error": None,
        "updated_utc": now,
    }})

    # Re-run the full workflow with existing metadata
    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"),
        doc.get("bc_document_no")
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}

@api_router.post("/documents/{doc_id}/link")
async def link_document(doc_id: str):
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
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()

    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    try:
        steps.append({"step": "validate_bc_record", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
        orders = await get_bc_sales_orders(order_no=bc_document_no)
        if orders:
            steps[-1]["status"] = "completed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "link_to_bc", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id or orders[0]["id"], 
                share_link=doc["sharepoint_share_link_url"], 
                file_name=doc["file_name"],
                file_content=file_content
            )
            if link_result.get("success"):
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = link_result
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "LinkedToBC", "updated_utc": datetime.now(timezone.utc).isoformat(), "last_error": None}})
                wf_status = "Completed"
            else:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = link_result.get("error", "Unknown error")
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": link_result.get("error"), "updated_utc": datetime.now(timezone.utc).isoformat()}})
                wf_status = "Failed"
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": "BC record not found", "updated_utc": datetime.now(timezone.utc).isoformat()}})
            wf_status = "Failed"

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": wf_status, "steps": steps, "correlation_id": correlation_id,
            "error": None if wf_status == "Completed" else steps[-1].get("error", "BC record not found")
        }
        await db.hub_workflow_runs.insert_one(workflow)
    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e)})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e)
        }
        await db.hub_workflow_runs.insert_one(workflow)

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": doc, "workflow_id": workflow_id}

# ==================== WORKFLOW ENDPOINTS ====================

@api_router.get("/workflows")
async def list_workflows(skip: int = Query(0), limit: int = Query(50), status: str = Query(None)):
    fq = {}
    if status:
        fq["status"] = status
    workflows = await db.hub_workflow_runs.find(fq, {"_id": 0}).sort("started_utc", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.hub_workflow_runs.count_documents(fq)
    return {"workflows": workflows, "total": total}

@api_router.get("/workflows/{wf_id}")
async def get_workflow(wf_id: str):
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf

@api_router.post("/workflows/{wf_id}/retry")
async def retry_workflow(wf_id: str):
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    doc_id = wf.get("document_id")
    if not doc_id:
        raise HTTPException(status_code=400, detail="No document associated with this workflow")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Associated document not found")
    if doc.get("sharepoint_share_link_url") and (doc.get("bc_record_id") or doc.get("bc_document_no")):
        result = await link_document(doc_id)
        return {"message": "Retry completed", "result": result}
    return {"message": "Cannot retry - document missing SharePoint link or BC reference"}

# ==================== DASHBOARD ====================

@api_router.get("/dashboard/stats")
async def get_dashboard_stats():
    total = await db.hub_documents.count_documents({})
    by_status = {}
    for s in ["Received", "Classified", "LinkedToBC", "Exception", "Completed"]:
        by_status[s] = await db.hub_documents.count_documents({"status": s})
    by_type = {}
    for t in ["SalesOrder", "SalesInvoice", "PurchaseInvoice", "PurchaseOrder", "Shipment", "Receipt", "Other"]:
        count = await db.hub_documents.count_documents({"document_type": t})
        if count > 0:
            by_type[t] = count
    recent_workflows = await db.hub_workflow_runs.find({}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    failed_workflows = await db.hub_workflow_runs.find({"status": "Failed"}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    return {
        "total_documents": total, "by_status": by_status, "by_type": by_type,
        "recent_workflows": recent_workflows, "failed_workflows": failed_workflows,
        "demo_mode": DEMO_MODE
    }

# ==================== BC PROXY ====================

@api_router.get("/bc/companies")
async def list_bc_companies():
    companies = await get_bc_companies()
    return {"companies": companies}

@api_router.get("/bc/sales-orders")
async def list_bc_sales_orders(search: str = Query(None)):
    try:
        orders = await get_bc_sales_orders(order_no=search)
        return {"orders": orders}
    except Exception as e:
        logger.warning("BC sales orders search failed: %s", str(e))
        return {"orders": [], "warning": str(e)}

# ==================== SETTINGS ====================

CONFIG_KEYS = [
    "TENANT_ID", "BC_ENVIRONMENT", "BC_COMPANY_NAME", "BC_CLIENT_ID",
    "BC_CLIENT_SECRET", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
    "SHAREPOINT_SITE_HOSTNAME", "SHAREPOINT_SITE_PATH", "SHAREPOINT_LIBRARY_NAME",
    "DEMO_MODE"
]
SECRET_KEYS = {"BC_CLIENT_SECRET", "GRAPH_CLIENT_SECRET"}

def _mask(val: str) -> str:
    """Mask a secret value showing only first 4 and last 4 chars."""
    if not val or len(val) < 10:
        return "****" if val else ""
    return val[:4] + "*" * (len(val) - 8) + val[-4:]

def _current_config():
    """Read live module-level config vars."""
    return {
        "TENANT_ID": TENANT_ID,
        "BC_ENVIRONMENT": BC_ENVIRONMENT,
        "BC_COMPANY_NAME": BC_COMPANY_NAME,
        "BC_CLIENT_ID": BC_CLIENT_ID,
        "BC_CLIENT_SECRET": BC_CLIENT_SECRET,
        "GRAPH_CLIENT_ID": GRAPH_CLIENT_ID,
        "GRAPH_CLIENT_SECRET": GRAPH_CLIENT_SECRET,
        "SHAREPOINT_SITE_HOSTNAME": SHAREPOINT_SITE_HOSTNAME,
        "SHAREPOINT_SITE_PATH": SHAREPOINT_SITE_PATH,
        "SHAREPOINT_LIBRARY_NAME": SHAREPOINT_LIBRARY_NAME,
        "DEMO_MODE": str(DEMO_MODE).lower(),
    }

async def _load_config_from_db():
    """Load saved config from MongoDB and apply to module globals."""
    global DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME
    global BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    global SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME

    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0, "_key": 0})
    if not saved:
        return
    if saved.get("TENANT_ID"):
        TENANT_ID = saved["TENANT_ID"]
    if saved.get("BC_ENVIRONMENT"):
        BC_ENVIRONMENT = saved["BC_ENVIRONMENT"]
    if saved.get("BC_COMPANY_NAME"):
        BC_COMPANY_NAME = saved["BC_COMPANY_NAME"]
    if saved.get("BC_CLIENT_ID"):
        BC_CLIENT_ID = saved["BC_CLIENT_ID"]
    if saved.get("BC_CLIENT_SECRET"):
        BC_CLIENT_SECRET = saved["BC_CLIENT_SECRET"]
    if saved.get("GRAPH_CLIENT_ID"):
        GRAPH_CLIENT_ID = saved["GRAPH_CLIENT_ID"]
    if saved.get("GRAPH_CLIENT_SECRET"):
        GRAPH_CLIENT_SECRET = saved["GRAPH_CLIENT_SECRET"]
    if saved.get("SHAREPOINT_SITE_HOSTNAME"):
        SHAREPOINT_SITE_HOSTNAME = saved["SHAREPOINT_SITE_HOSTNAME"]
    if saved.get("SHAREPOINT_SITE_PATH"):
        SHAREPOINT_SITE_PATH = saved["SHAREPOINT_SITE_PATH"]
    if saved.get("SHAREPOINT_LIBRARY_NAME"):
        SHAREPOINT_LIBRARY_NAME = saved["SHAREPOINT_LIBRARY_NAME"]
    if "DEMO_MODE" in saved:
        DEMO_MODE = str(saved["DEMO_MODE"]).lower() == "true"

@api_router.get("/settings/status")
async def get_settings_status():
    return {
        "demo_mode": DEMO_MODE,
        "connections": {
            "mongodb": {"status": "connected", "detail": "Configured"},
            "sharepoint": {
                "status": "configured" if (GRAPH_CLIENT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "site": SHAREPOINT_SITE_HOSTNAME or "Not set",
                "path": SHAREPOINT_SITE_PATH or "Not set",
                "library": SHAREPOINT_LIBRARY_NAME
            },
            "business_central": {
                "status": "configured" if (BC_CLIENT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "environment": BC_ENVIRONMENT or "Not set",
                "company": BC_COMPANY_NAME or "Not set"
            },
            "entra_id": {
                "status": "configured" if (TENANT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "tenant_id": (TENANT_ID[:8] + "...") if TENANT_ID else "Not set"
            }
        },
        "sharepoint_folders": list(set(FOLDER_MAP.values()))
    }

@api_router.get("/settings/config")
async def get_settings_config():
    """Return current config with secrets masked."""
    raw = _current_config()
    masked = {}
    for k, v in raw.items():
        masked[k] = _mask(v) if k in SECRET_KEYS else v
    return {"config": masked}

class ConfigUpdate(BaseModel):
    TENANT_ID: Optional[str] = None
    BC_ENVIRONMENT: Optional[str] = None
    BC_COMPANY_NAME: Optional[str] = None
    BC_CLIENT_ID: Optional[str] = None
    BC_CLIENT_SECRET: Optional[str] = None
    GRAPH_CLIENT_ID: Optional[str] = None
    GRAPH_CLIENT_SECRET: Optional[str] = None
    SHAREPOINT_SITE_HOSTNAME: Optional[str] = None
    SHAREPOINT_SITE_PATH: Optional[str] = None
    SHAREPOINT_LIBRARY_NAME: Optional[str] = None
    DEMO_MODE: Optional[str] = None

@api_router.put("/settings/config")
async def update_settings_config(update: ConfigUpdate):
    """Save config to MongoDB and reload in-memory. No .env write = no server restart."""
    global DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME
    global BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    global SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME

    # Load current saved config from DB
    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0}) or {"_key": "credentials"}

    # Merge updates — skip masked placeholder values, strip whitespace
    update_dict = update.model_dump(exclude_none=True)
    for key, val in update_dict.items():
        if val is not None and "****" not in val:
            saved[key] = val.strip() if isinstance(val, str) else val

    # Upsert into MongoDB
    await db.hub_config.update_one(
        {"_key": "credentials"},
        {"$set": saved},
        upsert=True
    )

    # Reload in-memory immediately
    TENANT_ID = saved.get("TENANT_ID", TENANT_ID)
    BC_ENVIRONMENT = saved.get("BC_ENVIRONMENT", BC_ENVIRONMENT)
    BC_COMPANY_NAME = saved.get("BC_COMPANY_NAME", BC_COMPANY_NAME)
    BC_CLIENT_ID = saved.get("BC_CLIENT_ID", BC_CLIENT_ID)
    BC_CLIENT_SECRET = saved.get("BC_CLIENT_SECRET", BC_CLIENT_SECRET)
    GRAPH_CLIENT_ID = saved.get("GRAPH_CLIENT_ID", GRAPH_CLIENT_ID)
    GRAPH_CLIENT_SECRET = saved.get("GRAPH_CLIENT_SECRET", GRAPH_CLIENT_SECRET)
    SHAREPOINT_SITE_HOSTNAME = saved.get("SHAREPOINT_SITE_HOSTNAME", SHAREPOINT_SITE_HOSTNAME)
    SHAREPOINT_SITE_PATH = saved.get("SHAREPOINT_SITE_PATH", SHAREPOINT_SITE_PATH)
    SHAREPOINT_LIBRARY_NAME = saved.get("SHAREPOINT_LIBRARY_NAME", SHAREPOINT_LIBRARY_NAME)
    DEMO_MODE = str(saved.get("DEMO_MODE", "true")).lower() == "true"

    logger.info("Configuration updated via UI. Demo mode: %s", DEMO_MODE)

    # Return fresh masked config
    raw = _current_config()
    masked = {k: (_mask(v) if k in SECRET_KEYS else v) for k, v in raw.items()}
    return {"message": "Configuration saved successfully", "config": masked}

@api_router.post("/settings/test-connection")
async def test_connection(service: str = Query(...)):
    """Quick connectivity test with detailed permission diagnostics."""
    if service == "graph":
        try:
            token = await get_graph_token()
            if token == "mock-graph-token":
                return {"service": "graph", "status": "demo", "detail": "Running in demo mode"}
            # Test site resolution
            async with httpx.AsyncClient(timeout=15.0) as c:
                site_resp = await c.get(
                    f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}",
                    headers={"Authorization": f"Bearer {token}"})
                if site_resp.status_code == 200:
                    site_data = site_resp.json()
                    return {"service": "graph", "status": "ok", "detail": f"Connected. Site: {site_data.get('displayName', 'OK')}"}
                elif site_resp.status_code in (401, 403):
                    return {"service": "graph", "status": "error",
                        "detail": f"Permission denied (HTTP {site_resp.status_code}). Your app registration needs 'Sites.ReadWrite.All' (Application permission, NOT Delegated). Go to Azure Portal > App Registrations > API Permissions > Add permission > Microsoft Graph > Application > Sites.ReadWrite.All > then click 'Grant admin consent'."}
                elif site_resp.status_code == 404:
                    return {"service": "graph", "status": "error",
                        "detail": f"Site not found (HTTP 404). Verify hostname='{SHAREPOINT_SITE_HOSTNAME}' and path='{SHAREPOINT_SITE_PATH}'. The path should be like '/sites/YourSiteName' (not a full URL)."}
                else:
                    return {"service": "graph", "status": "error",
                        "detail": f"Unexpected HTTP {site_resp.status_code}: {site_resp.json().get('error', {}).get('message', site_resp.text[:200])}"}
        except Exception as e:
            return {"service": "graph", "status": "error", "detail": str(e)}
    elif service == "bc":
        try:
            token = await get_bc_token()
            if token == "mock-bc-token":
                return {"service": "bc", "status": "demo", "detail": "Running in demo mode"}
            async with httpx.AsyncClient(timeout=15.0) as c:
                resp = await c.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies",
                    headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        return {"service": "bc", "status": "error", "detail": f"BC returned non-JSON response (HTTP 200): {resp.text[:200]}"}
                    companies = data.get("value", [])
                    return {"service": "bc", "status": "ok", "detail": f"Connected. Found {len(companies)} companies: {', '.join(c.get('displayName', c.get('name','?')) for c in companies[:3])}"}
                elif resp.status_code == 404:
                    if "NoEnvironment" in resp.text:
                        return {"service": "bc", "status": "error",
                            "detail": f"Environment '{BC_ENVIRONMENT}' does not exist. Check the exact name in BC admin center (it's case-sensitive)."}
                    return {"service": "bc", "status": "error", "detail": f"BC API not found (404): {resp.text[:200]}"}
                elif resp.status_code in (401, 403):
                    return {"service": "bc", "status": "error",
                        "detail": f"Permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role, and API.ReadWrite.All permission is granted."}
                else:
                    return {"service": "bc", "status": "error",
                        "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"service": "bc", "status": "error", "detail": str(e)}
    return {"service": service, "status": "unknown", "detail": "Unknown service"}

# ==================== PHASE 2: EMAIL PARSER AGENT ====================

# Emergent LLM Key for AI Classification
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# ==================== JOB TYPE MODELS ====================

class AutomationLevel:
    MANUAL_ONLY = 0       # Store + classify only, no auto-linking
    AUTO_LINK = 1         # Auto-link to existing BC records
    AUTO_CREATE_DRAFT = 2 # Create draft BC documents
    ADVANCED = 3          # Future: auto-populate lines, etc.

class POValidationMode:
    PO_REQUIRED = "PO_REQUIRED"           # PO must exist and match in BC
    PO_IF_PRESENT = "PO_IF_PRESENT"       # Validate PO if extracted, but don't fail if missing
    PO_NOT_REQUIRED = "PO_NOT_REQUIRED"   # Skip PO validation entirely

class VendorMatchMethod:
    EXACT_NO = "exact_no"           # Exact match on Vendor No
    EXACT_NAME = "exact_name"       # Exact match on Vendor Name
    NORMALIZED = "normalized"       # Normalized match (strip Inc, LLC, punctuation)
    ALIAS = "alias"                 # Alias lookup table
    FUZZY = "fuzzy"                 # Fuzzy match with score

# Default Job Type configurations - Production Grade
DEFAULT_JOB_TYPES = {
    "AP_Invoice": {
        "job_type": "AP_Invoice",
        "display_name": "AP Invoice (Vendor Invoice)",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.85,
        "min_confidence_to_auto_create_draft": 0.95,
        # PO Validation - use PO_IF_PRESENT for real-world flexibility
        "po_validation_mode": "PO_IF_PRESENT",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        # Vendor matching configuration
        "vendor_match_threshold": 0.80,  # Minimum score for auto-accept
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "AP_Invoices",
        "bc_entity": "purchaseInvoices",
        "required_extractions": ["vendor", "invoice_number", "amount"],
        "optional_extractions": ["po_number", "due_date", "line_items"],
        "enabled": True
    },
    "Sales_PO": {
        "job_type": "Sales_PO",
        "display_name": "Sales PO (Customer Purchase Order)",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.80,
        "min_confidence_to_auto_create_draft": 0.92,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Sales_POs",
        "bc_entity": "salesOrders",
        "required_extractions": ["customer", "po_number", "order_date"],
        "optional_extractions": ["amount", "ship_to", "line_items"],
        "enabled": True
    },
    "AR_Invoice": {
        "job_type": "AR_Invoice",
        "display_name": "AR Invoice (Outgoing Invoice)",
        "automation_level": 0,  # Manual only - these are our invoices
        "min_confidence_to_auto_link": 0.90,
        "min_confidence_to_auto_create_draft": 0.98,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "AR_Invoices",
        "bc_entity": "salesInvoices",
        "required_extractions": ["customer", "invoice_number", "amount"],
        "optional_extractions": ["due_date", "line_items"],
        "enabled": True
    },
    "Remittance": {
        "job_type": "Remittance",
        "display_name": "Remittance Advice (Payment Confirmation)",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.75,
        "min_confidence_to_auto_create_draft": 0.95,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.75,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Remittances",
        "bc_entity": "vendorPayments",
        "required_extractions": ["vendor", "payment_amount", "payment_date"],
        "optional_extractions": ["invoice_references", "check_number"],
        "enabled": True
    }
}

# Vendor Alias Map (company-specific)
VENDOR_ALIAS_MAP = {
    # "Alias on Invoice": "Vendor Name in BC"
    # Add company-specific aliases here
}

# Email config schema
class EmailWatchConfig(BaseModel):
    mailbox_address: str
    watch_folder: str = "Inbox"
    needs_review_folder: str = "Needs Review"
    processed_folder: str = "Processed"
    enabled: bool = True

class JobTypeConfig(BaseModel):
    job_type: str
    display_name: str
    automation_level: int = 1
    min_confidence_to_auto_link: float = 0.85
    min_confidence_to_auto_create_draft: float = 0.95
    # PO Validation: PO_REQUIRED, PO_IF_PRESENT, PO_NOT_REQUIRED
    po_validation_mode: str = "PO_IF_PRESENT"
    allow_duplicate_check_override: bool = False
    requires_human_review_if_exception: bool = True
    # Vendor matching
    vendor_match_threshold: float = 0.80
    vendor_match_strategies: List[str] = ["exact_no", "exact_name", "normalized", "fuzzy"]
    sharepoint_folder: str
    bc_entity: str
    required_extractions: List[str]
    optional_extractions: List[str] = []
    enabled: bool = True

class DocumentIntake(BaseModel):
    source: str = "email"
    sender: Optional[str] = None
    subject: Optional[str] = None
    attachment_name: str
    content_hash: str
    email_id: Optional[str] = None
    email_received_utc: Optional[str] = None

class AIClassificationResult(BaseModel):
    suggested_job_type: str
    confidence: float
    extracted_fields: dict
    validation_results: dict
    automation_decision: str  # "auto_link", "auto_create", "needs_review", "manual"
    reasoning: str

class ValidationCheck(BaseModel):
    check_name: str
    passed: bool
    details: str
    required: bool = True

# ==================== AI CLASSIFICATION SERVICE ====================

async def classify_document_with_ai(file_path: str, file_name: str) -> dict:
    """
    Use Gemini to analyze a document and extract structured data.
    Returns classification and extracted fields.
    """
    if not EMERGENT_LLM_KEY:
        return {
            "error": "EMERGENT_LLM_KEY not configured",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {}
        }
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
        
        # Determine MIME type
        ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
        mime_map = {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'tiff': 'image/tiff',
            'gif': 'image/gif',
            'txt': 'text/plain',
            'csv': 'text/csv',
            'html': 'text/html',
            'json': 'application/json',
            'xml': 'application/xml'
        }
        mime_type = mime_map.get(ext, 'text/plain')  # Default to text/plain for better compatibility
        
        # Initialize chat with Gemini (required for file attachments)
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"classify-{uuid.uuid4()}",
            system_message="""You are a document classification and data extraction AI for a business document management system.
            
Your job is to analyze business documents and:
1. Classify the document type (AP_Invoice, Sales_PO, AR_Invoice, Remittance, or Unknown)
2. Extract key fields based on the document type
3. Provide a confidence score (0.0 to 1.0) for your classification

For AP_Invoice (vendor invoices we receive):
- Extract: vendor name, invoice_number, amount, po_number (if present), due_date
- Look for "Invoice", "Bill To" addressing our company

For Sales_PO (purchase orders from our customers):
- Extract: customer name, po_number, order_date, amount, ship_to address
- Look for customer company names, "Purchase Order" header

For AR_Invoice (invoices we send to customers):
- Extract: customer name, invoice_number, amount, due_date
- Look for our company name as the sender/from

For Remittance (payment confirmations):
- Extract: vendor/customer, payment_amount, payment_date, invoice_references
- Look for "Remittance Advice", "Payment", check numbers

Always respond with valid JSON in this exact format:
{
    "document_type": "AP_Invoice|Sales_PO|AR_Invoice|Remittance|Unknown",
    "confidence": 0.0-1.0,
    "extracted_fields": {
        "vendor": "...",
        "customer": "...",
        "invoice_number": "...",
        "po_number": "...",
        "amount": "...",
        "due_date": "...",
        "payment_date": "...",
        "payment_amount": "..."
    },
    "reasoning": "Brief explanation of classification"
}

Only include fields that you can actually extract from the document. Leave out fields that are not present."""
        ).with_model("gemini", "gemini-2.5-flash")
        
        # Create file attachment
        file_content = FileContentWithMimeType(
            file_path=file_path,
            mime_type=mime_type
        )
        
        # Send for classification
        user_message = UserMessage(
            text="Please analyze this business document. Classify it and extract all relevant fields. Respond with JSON only.",
            file_contents=[file_content]
        )
        
        response = await chat.send_message(user_message)
        
        # Parse JSON response
        import json
        # Clean response - extract JSON from possible markdown code blocks
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                if line.startswith("```") and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)
        
        result = json.loads(response_text)
        
        return {
            "suggested_job_type": result.get("document_type", "Unknown"),
            "confidence": float(result.get("confidence", 0.0)),
            "extracted_fields": result.get("extracted_fields", {}),
            "reasoning": result.get("reasoning", "")
        }
        
    except Exception as e:
        logger.error("AI classification failed: %s", str(e))
        return {
            "error": str(e),
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
            "reasoning": f"Classification failed: {str(e)}"
        }

# ==================== FIELD NORMALIZATION ====================

import re
from dateutil import parser as date_parser

def normalize_extracted_fields(fields: dict) -> dict:
    """
    Normalize extracted fields before BC validation.
    - Convert amounts to decimal
    - Convert dates to ISO format
    - Clean up strings
    """
    normalized = {}
    
    for key, value in fields.items():
        if value is None:
            continue
            
        # Amount fields
        if key in ('amount', 'payment_amount', 'total', 'subtotal'):
            # Remove currency symbols, commas, spaces
            clean_amount = re.sub(r'[^\d.-]', '', str(value))
            try:
                normalized[key] = float(clean_amount) if clean_amount else None
                normalized[f"{key}_raw"] = value  # Keep original for display
            except ValueError:
                normalized[key] = None
                normalized[f"{key}_raw"] = value
        
        # Date fields
        elif key in ('due_date', 'invoice_date', 'order_date', 'payment_date'):
            try:
                parsed_date = date_parser.parse(str(value))
                normalized[key] = parsed_date.strftime('%Y-%m-%d')
                normalized[f"{key}_raw"] = value
            except Exception:
                normalized[key] = None
                normalized[f"{key}_raw"] = value
        
        # String fields - trim whitespace
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = value
    
    return normalized

def normalize_vendor_name(name: str) -> str:
    """
    Normalize vendor name for matching.
    Strips common suffixes, punctuation, and converts to lowercase.
    """
    if not name:
        return ""
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove common business suffixes
    suffixes = [
        r'\s*,?\s*(inc\.?|incorporated)$',
        r'\s*,?\s*(llc\.?|l\.l\.c\.?)$',
        r'\s*,?\s*(ltd\.?|limited)$',
        r'\s*,?\s*(corp\.?|corporation)$',
        r'\s*,?\s*(co\.?|company)$',
        r'\s*,?\s*(plc\.?)$',
        r'\s*,?\s*(gmbh)$',
        r'\s*,?\s*(ag)$',
    ]
    
    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    
    # Remove punctuation and extra spaces
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def calculate_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy match score between two strings.
    Uses simple token overlap ratio.
    """
    if not name1 or not name2:
        return 0.0
    
    tokens1 = set(normalize_vendor_name(name1).split())
    tokens2 = set(normalize_vendor_name(name2).split())
    
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    
    return len(intersection) / len(union)

# ==================== BC MATCHING SERVICE ====================

async def match_vendor_in_bc(
    vendor_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """
    Multi-strategy vendor matching against BC.
    Returns candidates and best match.
    """
    result = {
        "matched": False,
        "match_method": None,
        "selected_vendor": None,
        "vendor_candidates": [],
        "score": 0.0
    }
    
    if not vendor_name:
        return result
    
    normalized_input = normalize_vendor_name(vendor_name)
    
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Fetch all vendors (in production, use $top and pagination)
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,number,displayName", "$top": "500"}
        )
        
        if resp.status_code != 200:
            return result
        
        vendors = resp.json().get("value", [])
        
        # Check alias map first
        if "alias" in strategies and vendor_name in VENDOR_ALIAS_MAP:
            alias_target = VENDOR_ALIAS_MAP[vendor_name]
            for v in vendors:
                if v.get("displayName", "").lower() == alias_target.lower():
                    result["matched"] = True
                    result["match_method"] = "alias"
                    result["selected_vendor"] = v
                    result["score"] = 1.0
                    return result
        
        # Try each strategy in order
        candidates = []
        
        for vendor in vendors:
            vendor_display = vendor.get("displayName", "")
            vendor_number = vendor.get("number", "")
            
            # Exact match on number
            if "exact_no" in strategies:
                if vendor_number.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_no"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Exact match on name
            if "exact_name" in strategies:
                if vendor_display.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_name"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Normalized match
            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(vendor_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_vendor"] = vendor
                    result["score"] = 0.95
                    return result
            
            # Fuzzy match - collect all candidates
            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(vendor_name, vendor_display)
                if score > 0.3:  # Minimum threshold for candidate list
                    candidates.append({
                        "vendor": vendor,
                        "score": score,
                        "display_name": vendor_display,
                        "vendor_id": vendor.get("id")
                    })
        
        # Sort candidates by score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["vendor_candidates"] = candidates[:5]  # Top 5
        
        # Check if best fuzzy match meets threshold
        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_vendor"] = candidates[0]["vendor"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            # Have candidates but below threshold - needs review
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0
    
    return result

async def match_customer_in_bc(
    customer_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """
    Multi-strategy customer matching against BC.
    Similar to vendor matching but for customers.
    """
    result = {
        "matched": False,
        "match_method": None,
        "selected_customer": None,
        "customer_candidates": [],
        "score": 0.0
    }
    
    if not customer_name:
        return result
    
    normalized_input = normalize_vendor_name(customer_name)
    
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/customers",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,number,displayName", "$top": "500"}
        )
        
        if resp.status_code != 200:
            return result
        
        customers = resp.json().get("value", [])
        candidates = []
        
        for customer in customers:
            customer_display = customer.get("displayName", "")
            customer_number = customer.get("number", "")
            
            # Exact match on number
            if "exact_no" in strategies and customer_number.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_no"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result
            
            # Exact match on name
            if "exact_name" in strategies and customer_display.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_name"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result
            
            # Normalized match
            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(customer_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_customer"] = customer
                    result["score"] = 0.95
                    return result
            
            # Fuzzy match
            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(customer_name, customer_display)
                if score > 0.3:
                    candidates.append({
                        "customer": customer,
                        "score": score,
                        "display_name": customer_display,
                        "customer_id": customer.get("id")
                    })
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["customer_candidates"] = candidates[:5]
        
        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_customer"] = candidates[0]["customer"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0
    
    return result

async def validate_bc_match(job_type: str, extracted_fields: dict, job_config: dict) -> dict:
    """
    Validate extracted data against Business Central records.
    Returns structured validation results with candidates for review.
    """
    # Normalize fields first
    normalized_fields = normalize_extracted_fields(extracted_fields)
    
    validation_results = {
        "all_passed": True,
        "checks": [],
        "warnings": [],
        "bc_record_id": None,
        "bc_record_info": None,
        "vendor_candidates": [],
        "customer_candidates": [],
        "normalized_fields": normalized_fields
    }
    
    if DEMO_MODE or not BC_CLIENT_ID:
        validation_results["checks"].append({
            "check_name": "demo_mode",
            "passed": True,
            "details": "Running in demo mode - validation simulated",
            "required": False
        })
        return validation_results
    
    try:
        token = await get_bc_token()
        companies = await get_bc_companies()
        if not companies:
            validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "bc_connection",
                "passed": False,
                "details": "No BC companies found",
                "required": True
            })
            return validation_results
        
        company_id = companies[0]["id"]
        
        # Get matching configuration
        match_strategies = job_config.get("vendor_match_strategies", ["exact_no", "exact_name", "normalized", "fuzzy"])
        match_threshold = job_config.get("vendor_match_threshold", 0.80)
        po_mode = job_config.get("po_validation_mode", "PO_IF_PRESENT")
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            # Vendor match for AP_Invoice, Remittance
            if job_type in ("AP_Invoice", "Remittance"):
                vendor_name = normalized_fields.get("vendor") or extracted_fields.get("vendor", "")
                if vendor_name:
                    vendor_result = await match_vendor_in_bc(
                        vendor_name, match_strategies, match_threshold, token, company_id
                    )
                    
                    validation_results["vendor_candidates"] = vendor_result.get("vendor_candidates", [])
                    
                    if vendor_result["matched"]:
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": True,
                            "details": f"Found vendor via {vendor_result['match_method']}: {vendor_result['selected_vendor'].get('displayName')} (score: {vendor_result['score']:.0%})",
                            "required": True,
                            "match_method": vendor_result["match_method"],
                            "score": vendor_result["score"]
                        })
                        validation_results["bc_record_id"] = vendor_result["selected_vendor"].get("id")
                        validation_results["bc_record_info"] = vendor_result["selected_vendor"]
                    else:
                        validation_results["all_passed"] = False
                        details = f"No vendor found matching '{vendor_name}'"
                        if vendor_result["vendor_candidates"]:
                            top_candidate = vendor_result["vendor_candidates"][0]
                            details += f". Best candidate: {top_candidate['display_name']} ({top_candidate['score']:.0%})"
                        
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": False,
                            "details": details,
                            "required": True,
                            "candidates_available": len(vendor_result["vendor_candidates"]) > 0
                        })
                
                # PO validation based on mode
                po_number = normalized_fields.get("po_number") or extracted_fields.get("po_number", "")
                
                if po_mode == "PO_REQUIRED":
                    # PO must exist and match
                    if not po_number:
                        validation_results["all_passed"] = False
                        validation_results["checks"].append({
                            "check_name": "po_validation",
                            "passed": False,
                            "details": "PO number required but not extracted from document",
                            "required": True
                        })
                    else:
                        await _validate_po(c, token, company_id, po_number, validation_results, required=True)
                
                elif po_mode == "PO_IF_PRESENT":
                    # Validate only if PO was extracted
                    if po_number:
                        await _validate_po(c, token, company_id, po_number, validation_results, required=False)
                    else:
                        validation_results["warnings"].append({
                            "check_name": "po_not_present",
                            "details": "No PO number extracted - skipping PO validation"
                        })
                
                # else PO_NOT_REQUIRED - skip PO validation entirely
                
                # Duplicate invoice check
                invoice_number = normalized_fields.get("invoice_number") or extracted_fields.get("invoice_number")
                if invoice_number:
                    resp = await c.get(
                        f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"}
                    )
                    if resp.status_code == 200:
                        existing = resp.json().get("value", [])
                        if existing and not job_config.get("allow_duplicate_check_override"):
                            validation_results["all_passed"] = False
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": False,
                                "details": f"Duplicate invoice found: {invoice_number}",
                                "required": True,
                                "existing_invoice_id": existing[0].get("id")
                            })
                        else:
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": True,
                                "details": "No duplicate invoice found",
                                "required": True
                            })
            
            # Customer match for Sales_PO, AR_Invoice
            elif job_type in ("Sales_PO", "AR_Invoice"):
                customer_name = normalized_fields.get("customer") or extracted_fields.get("customer", "")
                if customer_name:
                    customer_result = await match_customer_in_bc(
                        customer_name, match_strategies, match_threshold, token, company_id
                    )
                    
                    validation_results["customer_candidates"] = customer_result.get("customer_candidates", [])
                    
                    if customer_result["matched"]:
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": True,
                            "details": f"Found customer via {customer_result['match_method']}: {customer_result['selected_customer'].get('displayName')} (score: {customer_result['score']:.0%})",
                            "required": True,
                            "match_method": customer_result["match_method"],
                            "score": customer_result["score"]
                        })
                        validation_results["bc_record_id"] = customer_result["selected_customer"].get("id")
                        validation_results["bc_record_info"] = customer_result["selected_customer"]
                    else:
                        validation_results["all_passed"] = False
                        details = f"No customer found matching '{customer_name}'"
                        if customer_result["customer_candidates"]:
                            top_candidate = customer_result["customer_candidates"][0]
                            details += f". Best candidate: {top_candidate['display_name']} ({top_candidate['score']:.0%})"
                        
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": False,
                            "details": details,
                            "required": True,
                            "candidates_available": len(customer_result["customer_candidates"]) > 0
                        })
    
    except Exception as e:
        logger.error("BC validation failed: %s", str(e))
        validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "bc_error",
            "passed": False,
            "details": f"BC validation error: {str(e)}",
            "required": True
        })
    
    return validation_results

async def _validate_po(c, token: str, company_id: str, po_number: str, validation_results: dict, required: bool):
    """Helper to validate PO number in BC."""
    resp = await c.get(
        f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders",
        headers={"Authorization": f"Bearer {token}"},
        params={"$filter": f"number eq '{po_number}'"}
    )
    if resp.status_code == 200:
        pos = resp.json().get("value", [])
        if pos:
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": True,
                "details": f"Found PO: {po_number}",
                "required": required
            })
        else:
            if required:
                validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": False,
                "details": f"PO '{po_number}' not found in BC",
                "required": required
            })
            if not required:
                validation_results["warnings"].append({
                    "check_name": "po_not_found",
                    "details": f"PO '{po_number}' was extracted but not found in BC - not blocking"
                })

# ==================== AUTOMATION DECISION ENGINE ====================

def make_automation_decision(
    job_config: dict,
    ai_confidence: float,
    validation_results: dict
) -> tuple:
    """
    Decision matrix for automation level.
    Returns (decision, reasoning, metadata)
    
    Metadata includes candidates if available for quick resolution.
    """
    automation_level = job_config.get("automation_level", 0)
    link_threshold = job_config.get("min_confidence_to_auto_link", 0.85)
    create_threshold = job_config.get("min_confidence_to_auto_create_draft", 0.95)
    requires_review = job_config.get("requires_human_review_if_exception", True)
    
    metadata = {
        "vendor_candidates": validation_results.get("vendor_candidates", []),
        "customer_candidates": validation_results.get("customer_candidates", []),
        "warnings": validation_results.get("warnings", [])
    }
    
    # Level 0: Manual only
    if automation_level == 0:
        return "manual", "Job type configured for manual processing only", metadata
    
    # Check validation results
    if not validation_results.get("all_passed", False):
        failed_checks = [c["check_name"] for c in validation_results.get("checks", []) if not c["passed"] and c.get("required", True)]
        
        # Check if we have candidates for failed checks (can be resolved with one click)
        has_candidates = (
            len(validation_results.get("vendor_candidates", [])) > 0 or
            len(validation_results.get("customer_candidates", [])) > 0
        )
        
        reason_suffix = ""
        if has_candidates:
            reason_suffix = " (candidates available for quick resolution)"
        
        if requires_review:
            return "needs_review", f"Validation failed: {', '.join(failed_checks)}{reason_suffix}", metadata
        return "manual", f"Validation failed but review not required: {', '.join(failed_checks)}", metadata
    
    # Check warnings (non-blocking issues)
    warning_notes = ""
    if validation_results.get("warnings"):
        warning_notes = f" (with {len(validation_results['warnings'])} warning(s))"
    
    # Check confidence thresholds
    if ai_confidence < link_threshold:
        return "needs_review", f"Confidence {ai_confidence:.2%} below link threshold {link_threshold:.2%}", metadata
    
    # Level 1: Auto-link only
    if automation_level == 1:
        if ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold, auto-linking to existing BC record{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below threshold", metadata
    
    # Level 2: Auto-create draft
    if automation_level >= 2:
        if ai_confidence >= create_threshold:
            return "auto_create", f"Confidence {ai_confidence:.2%} meets create threshold, creating draft BC document{warning_notes}", metadata
        elif ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold only, auto-linking{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below thresholds", metadata
    
    return "needs_review", "Default fallback to review", metadata

# ==================== EMAIL WATCHER SERVICE ====================

async def get_email_watcher_config() -> dict:
    """Load email watcher configuration from database."""
    config = await db.hub_config.find_one({"_key": "email_watcher"}, {"_id": 0})
    if not config:
        return {
            "mailbox_address": "",
            "watch_folder": "Inbox",
            "needs_review_folder": "Needs Review",
            "processed_folder": "Processed",
            "enabled": False,
            "webhook_subscription_id": None,
            "last_poll_utc": None
        }
    return config

async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """
    Create a Microsoft Graph subscription for email notifications.
    """
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "message": "Running in demo mode"}
    
    try:
        token = await get_graph_token()
        
        # Create subscription for new messages
        subscription_payload = {
            "changeType": "created",
            "notificationUrl": webhook_url,
            "resource": f"users/{mailbox_address}/mailFolders/Inbox/messages",
            "expirationDateTime": (datetime.now(timezone.utc).replace(hour=23, minute=59) + timedelta(days=2)).isoformat() + "Z",
            "clientState": "gpi-document-hub-secret"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=subscription_payload
            )
            
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "status": "ok",
                    "subscription_id": data.get("id"),
                    "expiration": data.get("expirationDateTime")
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create subscription (HTTP {resp.status_code}): {resp.text[:500]}"
                }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def fetch_email_with_attachments(email_id: str, mailbox_address: str) -> dict:
    """Fetch a specific email and its attachments from Graph API."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "email": None, "attachments": []}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=60.0) as c:
            # Get email details
            email_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if email_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to fetch email: {email_resp.status_code}"}
            
            email_data = email_resp.json()
            
            # Get attachments
            attachments_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/attachments",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            attachments = []
            if attachments_resp.status_code == 200:
                for att in attachments_resp.json().get("value", []):
                    if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                        attachments.append({
                            "id": att.get("id"),
                            "name": att.get("name"),
                            "content_type": att.get("contentType"),
                            "size": att.get("size"),
                            "content_bytes": att.get("contentBytes")  # Base64 encoded
                        })
            
            return {
                "status": "ok",
                "email": {
                    "id": email_data.get("id"),
                    "subject": email_data.get("subject"),
                    "sender": email_data.get("from", {}).get("emailAddress", {}).get("address"),
                    "received_utc": email_data.get("receivedDateTime"),
                    "has_attachments": email_data.get("hasAttachments", False)
                },
                "attachments": attachments
            }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def move_email_to_folder(email_id: str, mailbox_address: str, folder_name: str) -> dict:
    """Move an email to a specific folder."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo"}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            # First, find the folder ID
            folders_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if folders_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to list folders: {folders_resp.status_code}"}
            
            folder_id = None
            for folder in folders_resp.json().get("value", []):
                if folder.get("displayName") == folder_name:
                    folder_id = folder.get("id")
                    break
            
            if not folder_id:
                # Create the folder if it doesn't exist
                create_resp = await c.post(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json={"displayName": folder_name}
                )
                if create_resp.status_code in (200, 201):
                    folder_id = create_resp.json().get("id")
                else:
                    return {"status": "error", "message": f"Failed to create folder: {create_resp.status_code}"}
            
            # Move the email
            move_resp = await c.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/move",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"destinationId": folder_id}
            )
            
            if move_resp.status_code in (200, 201):
                return {"status": "ok", "folder": folder_name}
            else:
                return {"status": "error", "message": f"Failed to move email: {move_resp.status_code}"}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==================== EMAIL INTAKE ENDPOINTS ====================

@api_router.post("/documents/intake")
async def intake_document(
    file: UploadFile = File(...),
    source: str = Form("email"),
    sender: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    attachment_name: Optional[str] = Form(None),
    content_hash: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    email_received_utc: Optional[str] = Form(None)
):
    """
    Receive a document from email or other source.
    Runs AI classification and automation decision matrix.
    """
    file_content = await file.read()
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Use provided attachment name or fall back to filename
    final_filename = attachment_name or file.filename
    
    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)
    
    # Create document record
    doc = {
        "id": doc_id,
        "source": source,
        "file_name": final_filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "content_type": file.content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": email_received_utc,
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "document_type": None,
        "suggested_job_type": None,
        "ai_confidence": None,
        "extracted_fields": None,
        "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None,
        "bc_company_id": None,
        "bc_record_id": None,
        "bc_document_no": None,
        "status": "Received",
        "created_utc": now,
        "updated_utc": now,
        "last_error": None
    }
    await db.hub_documents.insert_one(doc)
    
    # Run AI classification
    logger.info("Running AI classification for document %s", doc_id)
    classification = await classify_document_with_ai(str(file_path), final_filename)
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning = make_automation_decision(job_configs, confidence, validation_results)
    
    # Update document with classification results
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        "validation_results": validation_results,
        "automation_decision": decision,
        "status": "Classified",
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }})
    
    # Create workflow run for intake
    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "email_intake",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": [
            {"step": "receive_document", "status": "completed", "result": {"source": source, "hash": computed_hash}},
            {"step": "ai_classification", "status": "completed", "result": classification},
            {"step": "bc_validation", "status": "completed", "result": validation_results},
            {"step": "automation_decision", "status": "completed", "result": {"decision": decision, "reasoning": reasoning}}
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    # Execute automation based on decision
    if decision == "auto_link" or decision == "auto_create":
        # Run the full upload and link workflow
        folder = job_configs.get("sharepoint_folder", "Incoming")
        
        try:
            # Upload to SharePoint
            sp_result = await upload_to_sharepoint(file_content, final_filename, folder)
            share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
            
            # Link to BC if we have a record
            bc_linked = False
            bc_record_id = validation_results.get("bc_record_id")
            
            if decision == "auto_link" and bc_record_id:
                # Find related sales order or create appropriate link
                link_result = await link_document_to_bc(
                    bc_record_id=bc_record_id,
                    share_link=share_link,
                    file_name=final_filename,
                    file_content=file_content
                )
                bc_linked = link_result.get("success", False)
            
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "sharepoint_drive_id": sp_result["drive_id"],
                "sharepoint_item_id": sp_result["item_id"],
                "sharepoint_web_url": sp_result["web_url"],
                "sharepoint_share_link_url": share_link,
                "bc_record_id": bc_record_id,
                "status": "LinkedToBC" if bc_linked else "Classified",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
        except Exception as e:
            logger.error("Auto-link failed for document %s: %s", doc_id, str(e))
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "Exception",
                "last_error": str(e),
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
    elif decision == "needs_review":
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "NeedsReview",
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }})
    
    # Return result
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning
    }

@api_router.post("/documents/{doc_id}/classify")
async def classify_document(doc_id: str):
    """Re-run AI classification on an existing document."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")
    
    classification = await classify_document_with_ai(str(file_path), doc["file_name"])
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning = make_automation_decision(job_configs, confidence, validation_results)
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        "validation_results": validation_results,
        "automation_decision": decision,
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }})
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning
    }

# ==================== GRAPH WEBHOOK ENDPOINT ====================

from datetime import timedelta

@api_router.post("/graph/webhook")
async def graph_webhook(request_data: dict = None):
    """
    Microsoft Graph webhook endpoint for email notifications.
    Handles both validation and notification requests.
    """
    # Handle validation request (Graph sends this when creating subscription)
    if request_data and "validationToken" in request_data:
        return request_data["validationToken"]
    
    # Handle notification
    if request_data and "value" in request_data:
        for notification in request_data.get("value", []):
            # Verify client state
            if notification.get("clientState") != "gpi-document-hub-secret":
                logger.warning("Invalid client state in webhook notification")
                continue
            
            resource = notification.get("resource", "")
            change_type = notification.get("changeType", "")
            
            if change_type == "created" and "/messages/" in resource:
                # Extract email ID and mailbox from resource
                # Resource format: users/{mailbox}/mailFolders/Inbox/messages/{emailId}
                parts = resource.split("/")
                if len(parts) >= 6:
                    mailbox = parts[1]
                    email_id = parts[-1]
                    
                    # Queue for processing (in production, use a proper queue)
                    logger.info("New email notification: mailbox=%s, email_id=%s", mailbox, email_id)
                    
                    # Process the email
                    await process_incoming_email(email_id, mailbox)
    
    return {"status": "ok"}

@api_router.get("/graph/webhook")
async def graph_webhook_validation(validationToken: str = Query(None)):
    """Handle Graph subscription validation (GET request)."""
    if validationToken:
        from starlette.responses import PlainTextResponse
        return PlainTextResponse(content=validationToken)
    return {"status": "ready"}

async def process_incoming_email(email_id: str, mailbox_address: str):
    """Process a new incoming email with attachments."""
    config = await get_email_watcher_config()
    
    if not config.get("enabled"):
        logger.info("Email watcher disabled, skipping email %s", email_id)
        return
    
    # Fetch email and attachments
    email_data = await fetch_email_with_attachments(email_id, mailbox_address)
    
    if email_data.get("status") != "ok":
        logger.error("Failed to fetch email %s: %s", email_id, email_data.get("message"))
        return
    
    email = email_data.get("email", {})
    attachments = email_data.get("attachments", [])
    
    if not attachments:
        logger.info("Email %s has no attachments, skipping", email_id)
        return
    
    # Process each attachment
    for attachment in attachments:
        import base64
        
        try:
            # Decode attachment content
            content_bytes = base64.b64decode(attachment.get("content_bytes", ""))
            
            # Create intake request
            intake = DocumentIntake(
                source="email",
                sender=email.get("sender"),
                subject=email.get("subject"),
                attachment_name=attachment.get("name"),
                content_hash=hashlib.sha256(content_bytes).hexdigest(),
                email_id=email_id,
                email_received_utc=email.get("received_utc")
            )
            
            # Save attachment temporarily
            temp_id = str(uuid.uuid4())
            temp_path = UPLOAD_DIR / temp_id
            temp_path.write_bytes(content_bytes)
            
            # Process through intake workflow
            doc_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            # Create document record
            doc = {
                "id": doc_id,
                "source": "email",
                "file_name": attachment.get("name"),
                "sha256_hash": intake.content_hash,
                "file_size": len(content_bytes),
                "content_type": attachment.get("content_type"),
                "email_sender": intake.sender,
                "email_subject": intake.subject,
                "email_id": email_id,
                "email_received_utc": intake.email_received_utc,
                "status": "Received",
                "created_utc": now,
                "updated_utc": now
            }
            await db.hub_documents.insert_one(doc)
            
            # Move temp file to permanent location
            perm_path = UPLOAD_DIR / doc_id
            temp_path.rename(perm_path)
            
            # Run classification
            classification = await classify_document_with_ai(str(perm_path), attachment.get("name"))
            
            suggested_type = classification.get("suggested_job_type", "Unknown")
            confidence = classification.get("confidence", 0.0)
            extracted_fields = classification.get("extracted_fields", {})
            
            # Get job config and validate
            job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
            
            validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
            decision, reasoning = make_automation_decision(job_configs, confidence, validation_results)
            
            # Update document
            new_status = "NeedsReview" if decision == "needs_review" else "Classified"
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "suggested_job_type": suggested_type,
                "document_type": suggested_type,
                "ai_confidence": confidence,
                "extracted_fields": extracted_fields,
                "validation_results": validation_results,
                "automation_decision": decision,
                "status": new_status,
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
            
            # Move email to appropriate folder
            if decision == "needs_review":
                await move_email_to_folder(email_id, mailbox_address, config.get("needs_review_folder", "Needs Review"))
            else:
                await move_email_to_folder(email_id, mailbox_address, config.get("processed_folder", "Processed"))
            
            logger.info("Processed email attachment: doc_id=%s, type=%s, decision=%s", doc_id, suggested_type, decision)
            
        except Exception as e:
            logger.error("Failed to process attachment from email %s: %s", email_id, str(e))

# ==================== JOB TYPE CONFIGURATION ENDPOINTS ====================

@api_router.get("/settings/job-types")
async def get_job_types():
    """Get all job type configurations."""
    job_types = await db.hub_job_types.find({}, {"_id": 0}).to_list(100)
    
    # Merge with defaults for any missing types
    result = dict(DEFAULT_JOB_TYPES)
    for jt in job_types:
        result[jt["job_type"]] = jt
    
    return {"job_types": list(result.values())}

@api_router.get("/settings/job-types/{job_type}")
async def get_job_type(job_type: str):
    """Get a specific job type configuration."""
    jt = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not jt:
        jt = DEFAULT_JOB_TYPES.get(job_type)
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
    return jt

@api_router.put("/settings/job-types/{job_type}")
async def update_job_type(job_type: str, config: JobTypeConfig):
    """Update a job type configuration."""
    update_data = config.model_dump()
    update_data["job_type"] = job_type
    
    await db.hub_job_types.update_one(
        {"job_type": job_type},
        {"$set": update_data},
        upsert=True
    )
    
    return await get_job_type(job_type)

@api_router.get("/settings/email-watcher")
async def get_email_watcher_settings():
    """Get email watcher configuration."""
    return await get_email_watcher_config()

@api_router.put("/settings/email-watcher")
async def update_email_watcher_settings(config: EmailWatchConfig):
    """Update email watcher configuration."""
    update_data = config.model_dump()
    update_data["_key"] = "email_watcher"
    
    await db.hub_config.update_one(
        {"_key": "email_watcher"},
        {"$set": update_data},
        upsert=True
    )
    
    return await get_email_watcher_config()

@api_router.post("/settings/email-watcher/subscribe")
async def subscribe_email_watcher(webhook_url: str = Query(...)):
    """Create Graph subscription for email notifications."""
    config = await get_email_watcher_config()
    
    if not config.get("mailbox_address"):
        raise HTTPException(status_code=400, detail="Mailbox address not configured")
    
    result = await subscribe_to_mailbox_notifications(config["mailbox_address"], webhook_url)
    
    if result.get("status") == "ok":
        await db.hub_config.update_one(
            {"_key": "email_watcher"},
            {"$set": {
                "webhook_subscription_id": result.get("subscription_id"),
                "webhook_expiration": result.get("expiration")
            }}
        )
    
    return result

# ==================== ENHANCED DASHBOARD ====================

@api_router.get("/dashboard/email-stats")
async def get_email_stats():
    """Get email processing statistics."""
    total_email = await db.hub_documents.count_documents({"source": "email"})
    needs_review = await db.hub_documents.count_documents({"source": "email", "status": "NeedsReview"})
    auto_linked = await db.hub_documents.count_documents({"source": "email", "status": "LinkedToBC"})
    
    # Get by job type
    by_job_type = {}
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({"source": "email", "suggested_job_type": jt})
        if count > 0:
            by_job_type[jt] = count
    
    # Recent email documents
    recent = await db.hub_documents.find(
        {"source": "email"},
        {"_id": 0}
    ).sort("created_utc", -1).limit(10).to_list(10)
    
    return {
        "total_email_documents": total_email,
        "needs_review": needs_review,
        "auto_linked": auto_linked,
        "by_job_type": by_job_type,
        "recent": recent
    }

# ==================== APP SETUP ====================

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup():
    await db.hub_documents.create_index("id", unique=True)
    await db.hub_documents.create_index("status")
    await db.hub_documents.create_index("document_type")
    await db.hub_documents.create_index("created_utc")
    await db.hub_documents.create_index("source")
    await db.hub_documents.create_index("suggested_job_type")
    await db.hub_workflow_runs.create_index("id", unique=True)
    await db.hub_workflow_runs.create_index("document_id")
    await db.hub_workflow_runs.create_index("started_utc")
    await db.hub_config.create_index("_key", unique=True)
    await db.hub_job_types.create_index("job_type", unique=True)
    # Load saved config from MongoDB (overrides .env defaults)
    await _load_config_from_db()
    # Initialize default job types if not present
    for jt_key, jt_config in DEFAULT_JOB_TYPES.items():
        existing = await db.hub_job_types.find_one({"job_type": jt_key})
        if not existing:
            await db.hub_job_types.insert_one(jt_config)
    logger.info("GPI Document Hub started. Demo mode: %s", DEMO_MODE)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
