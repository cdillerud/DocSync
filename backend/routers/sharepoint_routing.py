"""
GPI Document Hub - SharePoint Folder Routing Management Router

CRUD endpoints for managing folder routing rules, vendor mappings,
processor assignments, and document-to-folder suggestions.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sharepoint-routing", tags=["SharePoint Routing"])


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class FolderRuleCreate(BaseModel):
    folder_key: str = Field(..., description="Unique key like DROPSHIP_DOMESTIC")
    path: str = Field(..., description="SharePoint folder path")
    description: str = ""
    parent_key: Optional[str] = None
    subfolders: dict = Field(default_factory=dict)
    dynamic_subfolder_type: Optional[str] = None  # "by_year", "by_order", or None
    doc_types: list = Field(default_factory=list)  # Document types that route here
    sort_order: int = 0
    is_active: bool = True


class FolderRuleUpdate(BaseModel):
    path: Optional[str] = None
    description: Optional[str] = None
    subfolders: Optional[dict] = None
    dynamic_subfolder_type: Optional[str] = None
    doc_types: Optional[list] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class VendorMappingUpdate(BaseModel):
    vendor_pattern: str = Field(..., description="Vendor name pattern (lowercase)")
    folder_target: str = Field(..., description="Target folder name like 'Ball', 'Canpack'")
    vendor_category: str = "general"  # general, freight, dunnage


class ProcessorAssignment(BaseModel):
    folder_path: str
    processor_name: str
    is_active: bool = True


class FolderSuggestionRequest(BaseModel):
    doc_type: Optional[str] = None
    vendor: Optional[str] = None
    order_number: Optional[str] = None
    is_international: bool = False
    description: Optional[str] = None
    is_approved: bool = False
    has_freight_issue: bool = False


# ---------------------------------------------------------------------------
# Folder Structure Endpoints
# ---------------------------------------------------------------------------

@router.get("/folder-tree")
async def get_folder_tree():
    """Get the complete folder tree structure from DB (or defaults)."""
    db = get_db()

    rules = await db.sharepoint_folder_rules.find(
        {"is_active": True}, {"_id": 0}
    ).sort("sort_order", 1).to_list(200)

    if not rules:
        # Seed defaults and return
        rules = await _seed_default_rules(db)

    # Build tree
    tree = _build_tree(rules)

    return {
        "tree": tree,
        "rules": rules,
        "total_rules": len(rules),
    }


@router.get("/folder-rules")
async def list_folder_rules(include_inactive: bool = False):
    """List all folder routing rules."""
    db = get_db()
    query = {} if include_inactive else {"is_active": True}
    rules = await db.sharepoint_folder_rules.find(
        query, {"_id": 0}
    ).sort("sort_order", 1).to_list(200)

    if not rules:
        rules = await _seed_default_rules(db)

    return {"rules": rules, "total": len(rules)}


@router.post("/folder-rules")
async def create_folder_rule(rule: FolderRuleCreate):
    """Create a new folder routing rule."""
    db = get_db()

    existing = await db.sharepoint_folder_rules.find_one(
        {"folder_key": rule.folder_key}, {"_id": 0}
    )
    if existing:
        raise HTTPException(400, f"Rule with key '{rule.folder_key}' already exists")

    doc = {
        **rule.dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.sharepoint_folder_rules.insert_one(doc)

    return {"message": "Rule created", "rule": {k: v for k, v in doc.items() if k != "_id"}}


@router.put("/folder-rules/{folder_key}")
async def update_folder_rule(folder_key: str, updates: FolderRuleUpdate):
    """Update an existing folder routing rule."""
    db = get_db()

    update_data = {k: v for k, v in updates.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields to update")

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = await db.sharepoint_folder_rules.update_one(
        {"folder_key": folder_key},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Rule '{folder_key}' not found")

    updated = await db.sharepoint_folder_rules.find_one(
        {"folder_key": folder_key}, {"_id": 0}
    )
    return {"message": "Rule updated", "rule": updated}


@router.delete("/folder-rules/{folder_key}")
async def delete_folder_rule(folder_key: str):
    """Soft-delete a folder rule."""
    db = get_db()
    result = await db.sharepoint_folder_rules.update_one(
        {"folder_key": folder_key},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Rule '{folder_key}' not found")
    return {"message": f"Rule '{folder_key}' deactivated"}


# ---------------------------------------------------------------------------
# Vendor Mapping Endpoints
# ---------------------------------------------------------------------------

@router.get("/vendor-mappings")
async def list_vendor_mappings():
    """List all vendor-to-folder mappings."""
    db = get_db()
    mappings = await db.sharepoint_vendor_mappings.find(
        {}, {"_id": 0}
    ).sort("vendor_pattern", 1).to_list(500)

    if not mappings:
        mappings = await _seed_default_vendor_mappings(db)

    return {"mappings": mappings, "total": len(mappings)}


@router.post("/vendor-mappings")
async def create_vendor_mapping(mapping: VendorMappingUpdate):
    """Create a new vendor-to-folder mapping."""
    db = get_db()
    doc = {
        **mapping.dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.sharepoint_vendor_mappings.insert_one(doc)
    return {"message": "Mapping created", "mapping": {k: v for k, v in doc.items() if k != "_id"}}


@router.put("/vendor-mappings/{vendor_pattern}")
async def update_vendor_mapping(vendor_pattern: str, mapping: VendorMappingUpdate):
    """Update an existing vendor mapping."""
    db = get_db()
    result = await db.sharepoint_vendor_mappings.update_one(
        {"vendor_pattern": vendor_pattern},
        {"$set": {
            "folder_target": mapping.folder_target,
            "vendor_category": mapping.vendor_category,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Mapping for '{vendor_pattern}' not found")
    return {"message": "Mapping updated"}


@router.delete("/vendor-mappings/{vendor_pattern}")
async def delete_vendor_mapping(vendor_pattern: str):
    """Delete a vendor mapping."""
    db = get_db()
    result = await db.sharepoint_vendor_mappings.delete_one({"vendor_pattern": vendor_pattern})
    if result.deleted_count == 0:
        raise HTTPException(404, f"Mapping for '{vendor_pattern}' not found")
    return {"message": "Mapping deleted"}


# ---------------------------------------------------------------------------
# Processor Assignments
# ---------------------------------------------------------------------------

@router.get("/processor-assignments")
async def list_processor_assignments():
    """List all processor assignments (who processes what folders)."""
    db = get_db()
    assignments = await db.sharepoint_processor_assignments.find(
        {}, {"_id": 0}
    ).to_list(200)

    if not assignments:
        assignments = await _seed_default_processor_assignments(db)

    return {"assignments": assignments, "total": len(assignments)}


@router.post("/processor-assignments")
async def create_processor_assignment(assignment: ProcessorAssignment):
    """Create a new processor assignment."""
    db = get_db()
    doc = {
        **assignment.dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.sharepoint_processor_assignments.insert_one(doc)
    return {"message": "Assignment created", "assignment": {k: v for k, v in doc.items() if k != "_id"}}


@router.delete("/processor-assignments")
async def delete_processor_assignment(folder_path: str = Query(...), processor_name: str = Query(...)):
    """Delete a processor assignment."""
    db = get_db()
    await db.sharepoint_processor_assignments.delete_one({
        "folder_path": folder_path,
        "processor_name": processor_name,
    })
    return {"message": "Assignment deleted"}


# ---------------------------------------------------------------------------
# Document Folder Suggestion
# ---------------------------------------------------------------------------

@router.post("/suggest-folder")
async def suggest_folder(request: FolderSuggestionRequest):
    """Suggest a SharePoint folder path for a document based on routing rules."""
    from services.folder_routing_service import determine_folder_path

    # Build a mock doc dict from the request
    doc = {
        "document_type": request.doc_type or "Unknown",
        "suggested_job_type": request.doc_type or "Unknown",
        "extracted_fields": {
            "vendor": request.vendor or "",
            "description": request.description or "",
        },
        "normalized_fields": {
            "vendor": request.vendor or "",
        },
        "vendor_canonical": request.vendor or "",
        "po_number_extracted": request.order_number or "",
        "file_name": request.description or "",
        "approved": request.is_approved,
        "status": "Approved" if request.is_approved else "Pending",
        "needs_logistics_approval": request.has_freight_issue,
        "has_freight_issue": request.has_freight_issue,
    }

    folder_path, reason, details = determine_folder_path(
        doc=doc,
        is_international=request.is_international,
    )

    return {
        "suggested_folder": folder_path,
        "reason": reason,
        "details": details,
    }


@router.get("/document/{doc_id}/suggested-folder")
async def get_document_suggested_folder(doc_id: str):
    """Get the suggested SharePoint folder for a specific document."""
    db = get_db()
    from services.folder_routing_service import determine_folder_path

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    # Also check intelligence results for enrichment
    intel = await db.document_intelligence_results.find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    if intel:
        if intel.get("extracted_fields"):
            doc.setdefault("extracted_fields", {}).update(intel["extracted_fields"])
        if intel.get("document_type"):
            doc["document_type"] = intel["document_type"]

    folder_path, reason, details = determine_folder_path(doc=doc)

    return {
        "document_id": doc_id,
        "suggested_folder": folder_path,
        "reason": reason,
        "details": details,
        "file_name": doc.get("file_name", ""),
        "doc_type": doc.get("document_type") or doc.get("suggested_job_type", "Unknown"),
        "vendor": doc.get("vendor_canonical", ""),
    }


@router.post("/document/{doc_id}/assign-folder")
async def assign_folder_to_document(doc_id: str, folder_path: str = Body(..., embed=True)):
    """Manually assign a SharePoint folder path to a document."""
    db = get_db()
    result = await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "sharepoint_folder": folder_path,
            "sharepoint_folder_assigned_at": datetime.now(timezone.utc).isoformat(),
            "sharepoint_folder_assigned_by": "manual",
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Document {doc_id} not found")

    return {"message": f"Folder assigned: {folder_path}", "document_id": doc_id}


@router.post("/document/{doc_id}/move-to-sharepoint")
async def move_document_to_sharepoint(doc_id: str):
    """Move/copy a document to its assigned SharePoint folder."""
    db = get_db()
    from services.folder_routing_service import determine_folder_path
    from services.config_service import DEMO_MODE

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found")

    # Get or compute folder path
    folder_path = doc.get("sharepoint_folder")
    if not folder_path:
        folder_path, reason, _ = determine_folder_path(doc=doc)

    if DEMO_MODE:
        # In demo mode, simulate the move
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "sharepoint_folder": folder_path,
                "sharepoint_status": "moved_demo",
                "sharepoint_moved_at": datetime.now(timezone.utc).isoformat(),
            }}
        )
        return {
            "message": f"[DEMO] Document would be moved to: {folder_path}",
            "document_id": doc_id,
            "folder_path": folder_path,
            "demo_mode": True,
        }

    # Production: Use Graph API to move the file
    try:
        from services.config_service import get_graph_token, SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME
        import httpx

        token = await get_graph_token()
        file_name = doc.get("file_name", "unknown.pdf")

        # Get SharePoint site ID
        async with httpx.AsyncClient() as client:
            site_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if site_resp.status_code != 200:
                raise HTTPException(500, f"Failed to get SharePoint site: {site_resp.text}")
            site_id = site_resp.json()["id"]

            # Ensure destination folder exists
            folder_parts = folder_path.split("/")
            current_path = ""
            for part in folder_parts:
                parent_path = current_path or "root"
                current_path = f"{current_path}/{part}" if current_path else part
                try:
                    await client.post(
                        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{SHAREPOINT_LIBRARY_NAME}/{current_path}:/children",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                    )
                except Exception:
                    pass  # Folder may already exist

            # If the document has a SharePoint item ID, move it
            sp_item_id = doc.get("sharepoint_item_id") or doc.get("graph_item_id")
            if sp_item_id:
                move_resp = await client.patch(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{sp_item_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "parentReference": {
                            "path": f"/drive/root:/{SHAREPOINT_LIBRARY_NAME}/{folder_path}"
                        },
                        "name": file_name,
                    },
                )
                if move_resp.status_code not in (200, 201):
                    raise HTTPException(500, f"SharePoint move failed: {move_resp.text}")

                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "sharepoint_folder": folder_path,
                        "sharepoint_status": "moved",
                        "sharepoint_moved_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )
                return {
                    "message": f"Document moved to: {folder_path}",
                    "document_id": doc_id,
                    "folder_path": folder_path,
                    "demo_mode": False,
                }
            else:
                # No SharePoint item ID — upload the file if we have a local copy
                file_path = doc.get("file_path")
                if file_path:
                    import aiofiles
                    async with aiofiles.open(file_path, "rb") as f:
                        content = await f.read()
                    from urllib.parse import quote
                    safe_lib = quote(SHAREPOINT_LIBRARY_NAME, safe="/")
                    safe_folder = quote(folder_path, safe="/")
                    safe_name = quote(file_name, safe="")
                    upload_resp = await client.put(
                        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{safe_lib}/{safe_folder}/{safe_name}:/content",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream",
                        },
                        content=content,
                    )
                    if upload_resp.status_code not in (200, 201):
                        raise HTTPException(500, f"SharePoint upload failed: {upload_resp.text}")

                    new_item = upload_resp.json()
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {
                            "sharepoint_folder": folder_path,
                            "sharepoint_status": "uploaded",
                            "sharepoint_item_id": new_item.get("id"),
                            "sharepoint_moved_at": datetime.now(timezone.utc).isoformat(),
                        }}
                    )
                    return {
                        "message": f"Document uploaded to: {folder_path}",
                        "document_id": doc_id,
                        "folder_path": folder_path,
                        "demo_mode": False,
                    }
                else:
                    raise HTTPException(400, "No file path or SharePoint item ID available for this document")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("SharePoint move failed for %s: %s", doc_id, e)
        raise HTTPException(500, f"SharePoint move failed: {str(e)}")


@router.post("/batch-move")
async def batch_move_to_sharepoint(
    doc_ids: list = Body(..., embed=True),
):
    """Batch move documents to their assigned SharePoint folders."""
    results = {"success": [], "failed": [], "total": len(doc_ids)}

    for doc_id in doc_ids:
        try:
            result = await move_document_to_sharepoint(doc_id)
            results["success"].append({
                "document_id": doc_id,
                "folder_path": result["folder_path"],
            })
        except Exception as e:
            results["failed"].append({
                "document_id": doc_id,
                "error": str(e),
            })

    return results


@router.post("/batch-suggest")
async def batch_suggest_folders(
    doc_ids: list = Body(None, embed=True),
    doc_type: Optional[str] = Body(None, embed=True),
    limit: int = Body(50, embed=True),
):
    """Batch compute folder suggestions for multiple documents."""
    db = get_db()
    from services.folder_routing_service import determine_folder_path

    query = {}
    if doc_ids:
        query["id"] = {"$in": doc_ids}
    elif doc_type:
        query["$or"] = [
            {"document_type": doc_type},
            {"suggested_job_type": doc_type},
        ]

    docs = await db.hub_documents.find(
        query, {"_id": 0}
    ).limit(limit).to_list(limit)

    suggestions = []
    for doc in docs:
        folder_path, reason, details = determine_folder_path(doc=doc)
        suggestions.append({
            "document_id": doc.get("id"),
            "file_name": doc.get("file_name", ""),
            "doc_type": doc.get("document_type") or doc.get("suggested_job_type", "Unknown"),
            "vendor": doc.get("vendor_canonical", ""),
            "suggested_folder": folder_path,
            "reason": reason,
            "current_folder": doc.get("sharepoint_folder"),
        })

    return {"suggestions": suggestions, "total": len(suggestions)}


@router.post("/seed-defaults")
async def seed_defaults():
    """Re-seed default folder rules, vendor mappings, and processor assignments."""
    db = get_db()

    # Clear existing
    await db.sharepoint_folder_rules.delete_many({})
    await db.sharepoint_vendor_mappings.delete_many({})
    await db.sharepoint_processor_assignments.delete_many({})

    rules = await _seed_default_rules(db)
    mappings = await _seed_default_vendor_mappings(db)
    assignments = await _seed_default_processor_assignments(db)

    return {
        "message": "Defaults seeded",
        "rules": len(rules),
        "vendor_mappings": len(mappings),
        "processor_assignments": len(assignments),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_tree(rules):
    """Build a hierarchical tree from flat rules."""
    tree = []
    key_map = {r["folder_key"]: r for r in rules}

    for rule in rules:
        if not rule.get("parent_key"):
            node = {
                "key": rule["folder_key"],
                "path": rule["path"],
                "description": rule.get("description", ""),
                "children": [],
                "doc_types": rule.get("doc_types", []),
                "dynamic": rule.get("dynamic_subfolder_type"),
            }
            # Find children
            for child_rule in rules:
                if child_rule.get("parent_key") == rule["folder_key"]:
                    child_node = {
                        "key": child_rule["folder_key"],
                        "path": child_rule["path"],
                        "description": child_rule.get("description", ""),
                        "children": [],
                        "doc_types": child_rule.get("doc_types", []),
                        "dynamic": child_rule.get("dynamic_subfolder_type"),
                    }
                    # Find grandchildren
                    for gc_rule in rules:
                        if gc_rule.get("parent_key") == child_rule["folder_key"]:
                            child_node["children"].append({
                                "key": gc_rule["folder_key"],
                                "path": gc_rule["path"],
                                "description": gc_rule.get("description", ""),
                                "children": [],
                                "doc_types": gc_rule.get("doc_types", []),
                                "dynamic": gc_rule.get("dynamic_subfolder_type"),
                            })
                    node["children"].append(child_node)
            tree.append(node)

    return tree


async def _seed_default_rules(db):
    """Seed the default folder structure rules matching the accounting document."""
    rules = [
        # Top-level folders
        {"folder_key": "DO_NOT_PAY", "path": "DO NOT PAY Documents", "description": "Vendor invoices authorized not to pay", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": "by_year", "doc_types": ["DO_NOT_PAY"], "sort_order": 1, "is_active": True},
        {"folder_key": "DROPSHIP_INTERNATIONAL", "path": "Dropship International Documents", "description": "International vendor invoices for drop ship orders", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": "by_order", "doc_types": ["AP_Invoice", "Freight_Document", "Shipping_Document"], "sort_order": 2, "is_active": True},
        {"folder_key": "DROPSHIP_DOMESTIC", "path": "Dropship Not International Documents", "description": "Domestic vendor invoices for drop ship orders", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": "by_order", "doc_types": ["AP_Invoice", "Freight_Document", "Shipping_Document"], "sort_order": 3, "is_active": True},
        {"folder_key": "DROPSHIP_DOMESTIC_CANPACK", "path": "Canpack", "description": "All Canpack shipment documents", "parent_key": "DROPSHIP_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 31, "is_active": True},
        {"folder_key": "DROPSHIP_DOMESTIC_CANPACK_DUNNAGE", "path": "Dunnage return freight", "description": "Canpack dunnage return freight invoices", "parent_key": "DROPSHIP_DOMESTIC_CANPACK", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["Freight_Document"], "sort_order": 311, "is_active": True},
        {"folder_key": "FREIGHT_ISSUES", "path": "Freight Issues", "description": "Freight invoices needing logistics approval", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["Freight_Document"], "sort_order": 4, "is_active": True},
        {"folder_key": "READY_TO_PROCESS", "path": "Ready to process", "description": "Documents ready for processing", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 5, "is_active": True},
        {"folder_key": "READY_TO_PROCESS_PURCH_INV", "path": "Purch Inv", "description": "Invoices with cost verified, purchase invoice only", "parent_key": "READY_TO_PROCESS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["AP_Invoice"], "sort_order": 51, "is_active": True},
        {"folder_key": "MEG_TO_PROCESS", "path": "Meg to Process", "description": "Documents for Meg to process", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 6, "is_active": True},
        {"folder_key": "MISCELLANEOUS", "path": "Miscellaneous Documents", "description": "Miscellaneous office invoices", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["Unknown_Document", "OTHER"], "sort_order": 7, "is_active": True},
        {"folder_key": "MISC_APPROVED", "path": "Misc Invoices - approved", "description": "Approved miscellaneous invoices", "parent_key": "MISCELLANEOUS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 71, "is_active": True},
        {"folder_key": "MISC_NEED_APPROVAL", "path": "Misc Invoices - need approval", "description": "Miscellaneous invoices needing approval", "parent_key": "MISCELLANEOUS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 72, "is_active": True},
        {"folder_key": "RHONDA_ISSUES", "path": "Rhonda - Issues", "description": "Documents for Rhonda to process for issue resolution", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 8, "is_active": True},
        {"folder_key": "SH_APPROVED", "path": "S&H Invoices Approved Documents", "description": "Warehouse S&H invoices ready to process as cost only", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["AP_Invoice"], "sort_order": 9, "is_active": True},
        {"folder_key": "SH_APPROVED_ANDY", "path": "Andy to Process", "description": "S&H approved - Andy to process", "parent_key": "SH_APPROVED", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 91, "is_active": True},
        {"folder_key": "SH_APPROVED_ELLIE", "path": "Ellie to Process", "description": "S&H approved - Ellie to process", "parent_key": "SH_APPROVED", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 92, "is_active": True},
        {"folder_key": "SH_WAITING_APPROVAL", "path": "S&H Invoices waiting for approval Documents", "description": "Warehouse S&H invoices needing approval", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["AP_Invoice"], "sort_order": 10, "is_active": True},
        {"folder_key": "SH_WAITING_ANDY", "path": "Andy to Process", "description": "S&H waiting approval - Andy to process", "parent_key": "SH_WAITING_APPROVAL", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 101, "is_active": True},
        {"folder_key": "MONTH_REC_TEMPLATES", "path": "Month Rec & Templates", "description": "Monthly reconciliation and templates", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 11, "is_active": True},
        {"folder_key": "TOOLING", "path": "Tooling Invoices", "description": "Invoices for tooling charges", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["AP_Invoice"], "sort_order": 12, "is_active": True},
        {"folder_key": "VENDOR_CREDITS", "path": "Vendor Credit Memos", "description": "Vendor credit memos and related documents", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["Return_Request", "Remittance"], "sort_order": 13, "is_active": True},
        {"folder_key": "VC_ANCHOR_DUNNAGE", "path": "Anchor Dunnage", "description": "Anchor dunnage credits", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 131, "is_active": True},
        {"folder_key": "VC_BALL_DUNNAGE", "path": "Ball Dunnage", "description": "Ball dunnage credits", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 132, "is_active": True},
        {"folder_key": "VC_OI_DUNNAGE", "path": "OI Dunnage", "description": "OI dunnage credits", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 133, "is_active": True},
        {"folder_key": "VC_PROCESSED_AARON", "path": "Processed Credit Memo - Aaron", "description": "Processed credit memos by Aaron", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 134, "is_active": True},
        {"folder_key": "VC_SENT_TO_QUALITY", "path": "Sent to Quality", "description": "Credits sent to quality", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["Quality_Issue"], "sort_order": 135, "is_active": True},
        {"folder_key": "VC_UNCLAIMED", "path": "Unclaimed credits posted", "description": "Unclaimed posted credits", "parent_key": "VENDOR_CREDITS", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 136, "is_active": True},
        {"folder_key": "WAREHOUSE_INTERNATIONAL", "path": "Warehouse International Documents", "description": "International vendor invoices for warehouse orders", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": "by_order", "doc_types": ["AP_Invoice", "Shipping_Document"], "sort_order": 14, "is_active": True},
        {"folder_key": "WAREHOUSE_DOMESTIC", "path": "Warehouse Not International Documents", "description": "Domestic vendor invoices for warehouse orders", "parent_key": None, "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": ["AP_Invoice", "Shipping_Document"], "sort_order": 15, "is_active": True},
        {"folder_key": "WH_ASSEMBLY", "path": "Assembly", "description": "Assembly paperwork and invoices", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 151, "is_active": True},
        {"folder_key": "WH_GTS", "path": "GT's", "description": "GT's inbound paperwork", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 152, "is_active": True},
        {"folder_key": "WH_SORT_STACK", "path": "Sort and Stack", "description": "Sort and Stack inbound/assembly", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 153, "is_active": True},
        {"folder_key": "WH_ASSEMBLY_KENT", "path": "Assembly Kent", "description": "Assembly Kent inbound paperwork, freight, invoices", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 154, "is_active": True},
        {"folder_key": "WH_BALL_ORDERS", "path": "Ball Orders", "description": "Ball inbound/outbound paperwork and freight", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 155, "is_active": True},
        {"folder_key": "WH_GTS_ORDERS", "path": "GT's Orders", "description": "GT's outbound paperwork from Sort and Stack", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 156, "is_active": True},
        {"folder_key": "WH_TRANSFER_ORDERS", "path": "Transfer Orders", "description": "Transfer orders outbound paperwork", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 157, "is_active": True},
        {"folder_key": "WH_UPS_ORDERS", "path": "UPS Orders", "description": "UPS shipped orders outbound paperwork", "parent_key": "WAREHOUSE_DOMESTIC", "subfolders": {}, "dynamic_subfolder_type": None, "doc_types": [], "sort_order": 158, "is_active": True},
    ]

    now = datetime.now(timezone.utc).isoformat()
    for r in rules:
        r["created_at"] = now
        r["updated_at"] = now

    if rules:
        await db.sharepoint_folder_rules.insert_many(rules)

    # Return without _id
    return [{k: v for k, v in r.items() if k != "_id"} for r in rules]


async def _seed_default_vendor_mappings(db):
    """Seed default vendor-to-folder mappings."""
    mappings = [
        # Ball vendors
        {"vendor_pattern": "ball", "folder_target": "Ball", "vendor_category": "general"},
        {"vendor_pattern": "ball corporation", "folder_target": "Ball", "vendor_category": "general"},
        {"vendor_pattern": "ball container", "folder_target": "Ball", "vendor_category": "general"},
        {"vendor_pattern": "ball metal", "folder_target": "Ball", "vendor_category": "general"},
        # Canpack vendors
        {"vendor_pattern": "canpack", "folder_target": "Canpack", "vendor_category": "general"},
        {"vendor_pattern": "canpack group", "folder_target": "Canpack", "vendor_category": "general"},
        {"vendor_pattern": "canpack usa", "folder_target": "Canpack", "vendor_category": "general"},
        # Anchor vendors
        {"vendor_pattern": "anchor", "folder_target": "Anchor", "vendor_category": "general"},
        {"vendor_pattern": "anchor glass", "folder_target": "Anchor", "vendor_category": "general"},
        {"vendor_pattern": "anchor packaging", "folder_target": "Anchor", "vendor_category": "general"},
        # OI vendors
        {"vendor_pattern": "oi", "folder_target": "OI", "vendor_category": "general"},
        {"vendor_pattern": "o-i", "folder_target": "OI", "vendor_category": "general"},
        {"vendor_pattern": "owens illinois", "folder_target": "OI", "vendor_category": "general"},
        {"vendor_pattern": "owens-illinois", "folder_target": "OI", "vendor_category": "general"},
        # Freight carriers
        {"vendor_pattern": "ups", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "fedex", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "usps", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "dhl", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "xpo", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "old dominion", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "estes", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "saia", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "yrc", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "abf", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "r+l carriers", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "southeastern freight", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "averitt", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "dayton freight", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "central transport", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "pitt ohio", "folder_target": "Freight", "vendor_category": "freight"},
        {"vendor_pattern": "tumalo creek", "folder_target": "Freight", "vendor_category": "freight"},
    ]

    now = datetime.now(timezone.utc).isoformat()
    for m in mappings:
        m["created_at"] = now

    if mappings:
        await db.sharepoint_vendor_mappings.insert_many(mappings)

    return [{k: v for k, v in m.items() if k != "_id"} for m in mappings]


async def _seed_default_processor_assignments(db):
    """Seed default processor assignments."""
    assignments = [
        {"folder_path": "S&H Invoices Approved Documents/Andy to Process", "processor_name": "Andy", "is_active": True},
        {"folder_path": "S&H Invoices Approved Documents/Ellie to Process", "processor_name": "Ellie", "is_active": True},
        {"folder_path": "S&H Invoices waiting for approval Documents/Andy to Process", "processor_name": "Andy", "is_active": True},
        {"folder_path": "Meg to Process", "processor_name": "Meg", "is_active": True},
        {"folder_path": "Rhonda - Issues", "processor_name": "Rhonda", "is_active": True},
        {"folder_path": "Vendor Credit Memos/Processed Credit Memo - Aaron", "processor_name": "Aaron", "is_active": True},
    ]

    now = datetime.now(timezone.utc).isoformat()
    for a in assignments:
        a["created_at"] = now

    if assignments:
        await db.sharepoint_processor_assignments.insert_many(assignments)

    return [{k: v for k, v in a.items() if k != "_id"} for a in assignments]
