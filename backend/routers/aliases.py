"""GPI Document Hub - Vendor Aliases Router (Domain 2)

Extracted from server.py. Manages vendor alias CRUD operations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/aliases", tags=["Vendor Aliases"])


class VendorAlias(BaseModel):
    alias_string: str
    vendor_no: str
    vendor_name: Optional[str] = None
    confidence_override: Optional[float] = None
    notes: Optional[str] = None


@router.get("/vendors")
async def get_vendor_aliases():
    """Get all vendor aliases."""
    db = get_db()
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    return {"aliases": aliases, "count": len(aliases)}


@router.post("/vendors")
async def create_vendor_alias(alias: VendorAlias):
    """Create a new vendor alias mapping."""
    from server import normalize_vendor_name, VENDOR_ALIAS_MAP

    db = get_db()
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    normalized = normalize_vendor_name(alias.alias_string)

    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": alias.alias_string},
            {"normalized_alias": normalized}
        ]
    })

    if existing:
        raise HTTPException(status_code=400, detail=f"Alias already exists for '{alias.alias_string}'")

    alias_doc = {
        "alias_id": alias_id,
        "alias_string": alias.alias_string,
        "normalized_alias": normalized,
        "vendor_no": alias.vendor_no,
        "vendor_name": alias.vendor_name,
        "confidence_override": alias.confidence_override,
        "notes": alias.notes,
        "created_by": "system",
        "created_at": now,
        "usage_count": 0,
        "last_used_at": None
    }

    await db.vendor_aliases.insert_one(alias_doc)

    VENDOR_ALIAS_MAP[alias.alias_string] = alias.vendor_name or alias.vendor_no
    VENDOR_ALIAS_MAP[normalized] = alias.vendor_name or alias.vendor_no

    return {"alias_id": alias_id, "message": "Alias created successfully"}


@router.delete("/vendors/{alias_id}")
async def delete_vendor_alias(alias_id: str):
    """Delete a vendor alias."""
    db = get_db()
    result = await db.vendor_aliases.delete_one({"alias_id": alias_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"message": "Alias deleted"}


@router.get("/vendors/suggest")
async def suggest_alias_creation(
    vendor_name: str = Query(...),
    resolved_vendor_no: str = Query(...),
    resolved_vendor_name: str = Query(...)
):
    """
    Called when user manually resolves a vendor match.
    Returns suggestion to save as alias.
    """
    from server import normalize_vendor_name

    db = get_db()
    normalized = normalize_vendor_name(vendor_name)

    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": vendor_name},
            {"normalized_alias": normalized}
        ]
    }, {"_id": 0})

    if existing:
        return {
            "suggest_alias": False,
            "reason": "Alias already exists",
            "existing_alias": existing
        }

    return {
        "suggest_alias": True,
        "suggested_alias": {
            "alias_string": vendor_name,
            "normalized_alias": normalized,
            "vendor_no": resolved_vendor_no,
            "vendor_name": resolved_vendor_name
        },
        "message": f"Would you like to save '{vendor_name}' as an alias for '{resolved_vendor_name}'?"
    }


async def record_alias_usage(alias_string: str):
    """Record when an alias is used for matching."""
    db = get_db()
    await db.vendor_aliases.update_one(
        {"alias_string": alias_string},
        {
            "$inc": {"usage_count": 1},
            "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}
        }
    )
