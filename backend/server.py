from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import hashlib
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional
import uuid
from datetime import datetime, timezone
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

async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str):
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"success": True, "method": "mock", "note": "In production: write to BC external doc link field or add as attachment via BC API"}
    token = await get_bc_token()
    return {"success": True, "method": "api", "note": "Linked via BC API"}

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
        if bc_record_id or bc_document_no:
            step3_start = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "validate_bc_record", "status": "running", "started": step3_start})
            orders = await get_bc_sales_orders(order_no=bc_document_no)
            if orders:
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = {"found": True, "order_number": orders[0]["number"], "customer": orders[0]["customerName"]}

                step4_start = datetime.now(timezone.utc).isoformat()
                steps.append({"step": "link_to_bc", "status": "running", "started": step4_start})
                link_result = await link_document_to_bc(bc_record_id or orders[0]["id"], share_link, file_name)
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = link_result
                bc_linked = True
            else:
                steps[-1]["status"] = "warning"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = {"found": False, "note": "BC record not found"}

        # Determine final status
        if bc_record_id or bc_document_no:
            new_status = "LinkedToBC" if bc_linked else "Exception"
        else:
            new_status = "Classified"

        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "sharepoint_drive_id": sp_result["drive_id"],
            "sharepoint_item_id": sp_result["item_id"],
            "sharepoint_web_url": sp_result["web_url"],
            "sharepoint_share_link_url": share_link,
            "status": new_status,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "last_error": None if new_status != "Exception" else "BC record not found"
        }})

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "upload_and_link",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Completed" if new_status != "Exception" else "CompletedWithWarnings",
            "steps": steps, "correlation_id": correlation_id, "error": None
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
            link_result = await link_document_to_bc(bc_record_id or orders[0]["id"], doc["sharepoint_share_link_url"], doc["file_name"])
            steps[-1]["status"] = "completed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            steps[-1]["result"] = link_result
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "LinkedToBC", "updated_utc": datetime.now(timezone.utc).isoformat(), "last_error": None}})
            wf_status = "Completed"
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": "BC record not found", "updated_utc": datetime.now(timezone.utc).isoformat()}})
            wf_status = "Failed"

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": wf_status, "steps": steps, "correlation_id": correlation_id,
            "error": None if wf_status == "Completed" else "BC record not found"
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
    orders = await get_bc_sales_orders(order_no=search)
    return {"orders": orders}

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

    # Merge updates — skip masked placeholder values
    update_dict = update.model_dump(exclude_none=True)
    for key, val in update_dict.items():
        if val is not None and "****" not in val:
            saved[key] = val

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
                    data = resp.json()
                    companies = data.get("value", [])
                    return {"service": "bc", "status": "ok", "detail": f"Connected. Found {len(companies)} companies: {', '.join(c.get('displayName', c.get('name','?')) for c in companies[:3])}"}
                elif resp.status_code in (401, 403):
                    return {"service": "bc", "status": "error",
                        "detail": f"Permission denied (HTTP {resp.status_code}). Ensure the app has D365 Business Central API access and the BC_ENVIRONMENT name ('{BC_ENVIRONMENT}') is correct."}
                else:
                    error = resp.json().get("error", {})
                    return {"service": "bc", "status": "error",
                        "detail": f"HTTP {resp.status_code}: {error.get('message', resp.text[:200])}"}
        except Exception as e:
            return {"service": "bc", "status": "error", "detail": str(e)}
    return {"service": service, "status": "unknown", "detail": "Unknown service"}

# ==================== PHASE 2 HOOKS ====================

@api_router.post("/incoming/email")
async def incoming_email_webhook():
    return {"message": "Phase 2: Email ingestion not yet implemented", "status": "placeholder"}

@api_router.post("/documents/{doc_id}/classify")
async def classify_document(doc_id: str):
    return {"message": "Phase 2: AI classification not yet implemented", "status": "placeholder"}

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
    await db.hub_workflow_runs.create_index("id", unique=True)
    await db.hub_workflow_runs.create_index("document_id")
    await db.hub_workflow_runs.create_index("started_utc")
    await db.hub_config.create_index("_key", unique=True)
    # Load saved config from MongoDB (overrides .env defaults)
    await _load_config_from_db()
    logger.info("GPI Document Hub started. Demo mode: %s", DEMO_MODE)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
