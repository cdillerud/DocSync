"""Human routing review endpoints.

Provides folder-level routing options and turns a reviewer-selected destination
into a live routing-learning signal. The learned rule is consulted before the
hard-coded folder-routing rules on future documents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from hub_platform.bootstrap import get_platform_database
from pydantic import BaseModel, Field


router = APIRouter(prefix="/human-routing-review", tags=["Human Routing Review"])


class HumanRoutingAssignment(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Relative SharePoint folder path")
    source: str = Field(default="human_decision_queue", max_length=100)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "international", "intl"}


def _document_profile(doc: Dict[str, Any]) -> Dict[str, Any]:
    extracted = doc.get("extracted_fields") or {}
    normalized = doc.get("normalized_fields") or {}
    vendor = (
        doc.get("vendor_canonical")
        or doc.get("vendor_raw")
        or normalized.get("vendor")
        or extracted.get("vendor")
        or doc.get("sender")
        or ""
    )
    doc_type = (
        doc.get("doc_type")
        or doc.get("document_type")
        or doc.get("suggested_job_type")
        or "Unknown"
    )
    po_number = str(
        doc.get("po_number_extracted")
        or extracted.get("po_number")
        or extracted.get("order_number")
        or ""
    ).strip()
    is_international = _is_truthy(doc.get("is_international")) or _is_truthy(
        extracted.get("is_international")
    )
    current_folder = (
        doc.get("sharepoint_folder")
        or doc.get("sharepoint_folder_path")
        or doc.get("filed_to")
        or ""
    )
    return {
        "vendor": str(vendor).strip(),
        "doc_type": str(doc_type).strip() or "Unknown",
        "po_number": po_number,
        "has_po": bool(po_number),
        "is_international": is_international,
        "current_folder": str(current_folder).strip(),
        "extracted_fields": extracted,
    }


def _normalize_path(path: str) -> str:
    normalized = "/".join(part.strip() for part in path.replace("\\", "/").split("/") if part.strip())
    if not normalized:
        raise HTTPException(status_code=400, detail="A destination folder is required")
    if any(part == ".." for part in normalized.split("/")):
        raise HTTPException(status_code=400, detail="Parent-folder traversal is not allowed")
    return normalized


def _flatten_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key = {rule.get("folder_key"): rule for rule in rules if rule.get("folder_key")}
    cache: Dict[str, str] = {}

    def full_path(rule: Dict[str, Any], stack: set[str] | None = None) -> str:
        key = rule.get("folder_key") or ""
        if key in cache:
            return cache[key]
        stack = set(stack or set())
        if key in stack:
            return str(rule.get("path") or "").strip()
        stack.add(key)
        own = str(rule.get("path") or "").strip().strip("/")
        parent_key = rule.get("parent_key")
        parent = by_key.get(parent_key)
        value = f"{full_path(parent, stack)}/{own}" if parent and own else own
        cache[key] = value.strip("/")
        return cache[key]

    options = []
    for rule in rules:
        path = full_path(rule)
        if not path:
            continue
        options.append(
            {
                "key": rule.get("folder_key", ""),
                "path": path,
                "description": rule.get("description", ""),
                "doc_types": rule.get("doc_types", []),
                "dynamic_subfolder_type": rule.get("dynamic_subfolder_type"),
                "sort_order": rule.get("sort_order", 0),
            }
        )
    options.sort(key=lambda item: (item.get("sort_order", 0), item["path"].lower()))
    return options


@router.get("/folder-options")
async def get_folder_options(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Return selectable folder-level destinations from the live routing configuration."""
    rules = await database.sharepoint_folder_rules.find(
        {"is_active": {"$ne": False}}, {"_id": 0}
    ).sort("sort_order", 1).to_list(500)

    if rules:
        options = _flatten_rules(rules)
        source = "sharepoint_folder_rules"
    else:
        from services.folder_routing_service import get_all_folder_paths

        options = [
            {
                "key": "",
                "path": path,
                "description": "",
                "doc_types": [],
                "dynamic_subfolder_type": None,
                "sort_order": index,
            }
            for index, path in enumerate(get_all_folder_paths(), start=1)
        ]
        source = "folder_routing_service_defaults"

    return {"options": options, "total": len(options), "source": source}


@router.get("/document/{doc_id}/suggestion")
async def get_routing_suggestion(doc_id: str, database: AsyncIOMotorDatabase = Depends(get_platform_database)):
    """Return the current folder and the AI/learned routing suggestion for one document."""
    doc = await database.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    profile = _document_profile(doc)
    from services.folder_routing_service import route_with_feedback

    suggested_folder, reason, details = await route_with_feedback(
        doc=doc,
        is_international=profile["is_international"],
    )

    return {
        "document_id": doc_id,
        "file_name": doc.get("file_name", ""),
        "current_folder": profile["current_folder"],
        "suggested_folder": suggested_folder,
        "reason": reason,
        "details": details,
        "vendor": profile["vendor"],
        "doc_type": profile["doc_type"],
        "has_po": profile["has_po"],
        "is_international": profile["is_international"],
    }


@router.post("/document/{doc_id}/assign")
async def assign_reviewed_folder(doc_id: str, assignment: HumanRoutingAssignment, database: AsyncIOMotorDatabase = Depends(get_platform_database)):
    """Save a human folder decision and immediately teach the live routing learner."""
    doc = await database.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    selected_folder = _normalize_path(assignment.folder_path)
    profile = _document_profile(doc)

    from services.folder_routing_service import route_with_feedback

    suggested_folder, suggested_reason, suggested_details = await route_with_feedback(
        doc=doc,
        is_international=profile["is_international"],
    )
    comparison_folder = profile["current_folder"] or suggested_folder or ""
    is_confirmation = comparison_folder.strip().lower() == selected_folder.lower()
    decision_type = "folder_confirmation" if is_confirmation else "folder_correction"
    now = datetime.now(timezone.utc).isoformat()

    learning_result: Dict[str, Any]
    if profile["vendor"]:
        from services.routing_feedback_service import init_feedback_db, record_correction

        init_feedback_db(database)
        learning_result = await record_correction(
            vendor=profile["vendor"],
            doc_type=profile["doc_type"],
            has_po=profile["has_po"],
            is_international=profile["is_international"],
            correct_folder=selected_folder,
            file_name=doc.get("file_name", ""),
            source=assignment.source,
        )
    else:
        learning_result = {
            "status": "skipped_no_vendor",
            "reason": "No vendor or sender signal was available for a safe reusable rule",
        }

    decision_record = {
        "document_id": doc_id,
        "file_name": doc.get("file_name", ""),
        "decision_type": decision_type,
        "previous_folder": profile["current_folder"],
        "suggested_folder": suggested_folder,
        "suggested_reason": suggested_reason,
        "selected_folder": selected_folder,
        "vendor": profile["vendor"],
        "doc_type": profile["doc_type"],
        "has_po": profile["has_po"],
        "is_international": profile["is_international"],
        "source": assignment.source,
        "learning_result": learning_result,
        "created_at": now,
    }

    await database.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "sharepoint_folder": selected_folder,
                "sharepoint_folder_path": selected_folder,
                "sharepoint_folder_assigned_at": now,
                "sharepoint_folder_assigned_by": assignment.source,
                "human_routing_decision": decision_record,
            }
        },
    )
    await database.human_routing_decisions.insert_one(decision_record)
    decision_record.pop("_id", None)

    return {
        "message": f"Folder assigned: {selected_folder}",
        "document_id": doc_id,
        "folder_path": selected_folder,
        "decision_type": decision_type,
        "suggested_folder": suggested_folder,
        "suggested_reason": suggested_reason,
        "suggested_details": suggested_details,
        "learning": learning_result,
        "decision": decision_record,
    }
