"""
GPI Document Hub - Spiro Integration API Routes

Admin and debug endpoints for Spiro integration:
- OAuth callback for initial authorization
- Manual sync triggers
- Sync status inspection
- Document SpiroContext debugging
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create router
spiro_router = APIRouter(prefix="/api/spiro", tags=["Spiro Integration"])

# Database reference (set during app startup)
db = None

def set_spiro_routes_db(database):
    """Set database reference for Spiro routes."""
    global db
    db = database


# =============================================================================
# MODELS
# =============================================================================

class OAuthCallbackRequest(BaseModel):
    """Request model for OAuth callback."""
    code: str


class SyncRequest(BaseModel):
    """Request model for manual sync."""
    force_full: bool = False
    entity_types: Optional[list] = None  # None = all types


# =============================================================================
# CONFIGURATION ENDPOINTS
# =============================================================================

@spiro_router.get("/status")
async def get_spiro_status():
    """
    Get Spiro integration status.
    
    Returns configuration status, sync status, and collection counts.
    """
    from services.spiro import get_spiro_client
    from services.spiro.spiro_client import is_spiro_enabled
    from services.spiro.spiro_sync import get_spiro_sync_status
    
    client = get_spiro_client()
    
    return {
        "enabled": is_spiro_enabled(),
        "configured": client.is_configured(),
        "has_token": client.token_manager.get_access_token() is not None,
        "has_refresh_token": client.token_manager.get_refresh_token() is not None,
        "sync_status": await get_spiro_sync_status() if db is not None else {"error": "DB not initialized"}
    }


@spiro_router.get("/config")
async def get_spiro_config():
    """
    Get Spiro configuration (sanitized - no secrets).
    """
    from services.spiro.spiro_client import (
        is_spiro_enabled, SPIRO_API_BASE, SPIRO_OAUTH_URL
    )
    from services.spiro.spiro_context import SPIRO_CONTEXT_ENABLED
    
    return {
        "enabled": is_spiro_enabled(),
        "context_enabled": SPIRO_CONTEXT_ENABLED,
        "api_base": SPIRO_API_BASE,
        "oauth_url": SPIRO_OAUTH_URL,
        "client_id_configured": bool(os.environ.get("SPIRO_CLIENT_ID")),
        "client_secret_configured": bool(os.environ.get("SPIRO_CLIENT_SECRET")),
        "redirect_uri": os.environ.get("SPIRO_REDIRECT_URI", "http://localhost:8001/api/spiro/callback")
    }


# =============================================================================
# OAUTH ENDPOINTS
# =============================================================================

@spiro_router.get("/auth-url")
async def get_auth_url():
    """
    Get the Spiro OAuth authorization URL.
    
    User should visit this URL in browser to authorize the app.
    """
    client_id = os.environ.get("SPIRO_CLIENT_ID")
    redirect_uri = os.environ.get("SPIRO_REDIRECT_URI", "http://localhost:8001/api/spiro/callback")
    
    if not client_id:
        raise HTTPException(status_code=500, detail="SPIRO_CLIENT_ID not configured")
    
    # Spiro OAuth authorization URL
    auth_url = f"https://engine.spiro.ai/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"
    
    return {
        "auth_url": auth_url,
        "instructions": "Visit this URL in your browser. After authorization, you'll be redirected with a 'code' parameter. Use POST /api/spiro/callback with that code."
    }


@spiro_router.post("/callback")
async def oauth_callback(request: OAuthCallbackRequest):
    """
    Exchange authorization code for access token.
    
    Called after user authorizes the app in browser.
    """
    from services.spiro import get_spiro_client
    
    client = get_spiro_client()
    
    if not client.is_configured():
        raise HTTPException(status_code=500, detail="Spiro credentials not configured")
    
    success = await client.exchange_authorization_code(request.code)
    
    if success:
        return {
            "success": True,
            "message": "Spiro authorization successful. You can now sync data."
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")


@spiro_router.get("/callback")
async def oauth_callback_get(code: str = Query(...)):
    """
    OAuth callback handler for browser redirect.
    
    Spiro will redirect here with ?code=... after user authorizes.
    """
    from services.spiro import get_spiro_client
    
    client = get_spiro_client()
    
    if not client.is_configured():
        raise HTTPException(status_code=500, detail="Spiro credentials not configured")
    
    success = await client.exchange_authorization_code(code)
    
    if success:
        return {
            "success": True,
            "message": "Spiro authorization successful! You can close this window and return to GPI Hub."
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")


# =============================================================================
# SYNC ENDPOINTS
# =============================================================================

@spiro_router.post("/sync")
async def trigger_sync(request: SyncRequest = None):
    """
    Trigger a manual Spiro data sync.
    
    Args:
        force_full: If true, ignore last sync time and sync all records
        entity_types: List of entity types to sync (contacts, companies, opportunities)
                     If not provided, syncs all types
    """
    from services.spiro.spiro_client import is_spiro_enabled
    from services.spiro.spiro_sync import SpiroSyncService
    
    if not is_spiro_enabled():
        raise HTTPException(status_code=400, detail="Spiro integration is disabled")
    
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    request = request or SyncRequest()
    service = SpiroSyncService(db)
    
    entity_types = request.entity_types or ["contacts", "companies", "opportunities"]
    results = {}
    
    if "contacts" in entity_types:
        results["contacts"] = await service.sync_contacts(request.force_full)
    
    if "companies" in entity_types:
        results["companies"] = await service.sync_companies(request.force_full)
    
    if "opportunities" in entity_types:
        results["opportunities"] = await service.sync_opportunities(request.force_full)
    
    total_records = sum(r.get("records", 0) for r in results.values())
    all_success = all(r.get("success", False) for r in results.values())
    
    return {
        "success": all_success,
        "total_records": total_records,
        "results": results,
        "synced_at": datetime.now(timezone.utc).isoformat()
    }


@spiro_router.post("/sync/contacts")
async def sync_contacts(force_full: bool = False):
    """Sync only contacts from Spiro."""
    from services.spiro import sync_spiro_contacts
    return await sync_spiro_contacts(force_full)


@spiro_router.post("/sync/all")
async def sync_all(force_full: bool = False):
    """Sync all Spiro data (contacts, companies, opportunities)."""
    from services.spiro import sync_all_spiro_data
    return await sync_all_spiro_data(force_full)


# =============================================================================
# DATA INSPECTION ENDPOINTS
# =============================================================================

@spiro_router.get("/companies")
async def list_spiro_companies(
    search: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """
    List synced Spiro companies.
    
    Args:
        search: Optional search term for company name
        limit: Maximum results to return
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    query = {}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    
    cursor = db.spiro_companies.find(query, {"_id": 0}).limit(limit)
    companies = await cursor.to_list(length=limit)
    
    return {
        "companies": companies,
        "count": len(companies)
    }


@spiro_router.get("/contacts")
async def list_spiro_contacts(
    search: Optional[str] = None,
    company_id: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """
    List synced Spiro contacts.
    
    Args:
        search: Optional search term for contact name/email
        company_id: Filter by Spiro company ID
        limit: Maximum results to return
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    query = {}
    if search:
        query["$or"] = [
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]
    if company_id:
        query["company_id"] = company_id
    
    cursor = db.spiro_contacts.find(query, {"_id": 0}).limit(limit)
    contacts = await cursor.to_list(length=limit)
    
    return {
        "contacts": contacts,
        "count": len(contacts)
    }


@spiro_router.get("/opportunities")
async def list_spiro_opportunities(
    company_id: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """List synced Spiro opportunities."""
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    query = {}
    if company_id:
        query["company_id"] = company_id
    
    cursor = db.spiro_opportunities.find(query, {"_id": 0}).limit(limit)
    opportunities = await cursor.to_list(length=limit)
    
    return {
        "opportunities": opportunities,
        "count": len(opportunities)
    }


# =============================================================================
# DOCUMENT CONTEXT ENDPOINTS
# =============================================================================

@spiro_router.get("/context/{doc_id}")
async def get_document_spiro_context(doc_id: str):
    """
    Get SpiroContext for a specific document.
    
    Useful for debugging and inspecting what Spiro data matches a document.
    """
    from services.spiro import get_spiro_context_for_document
    
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Get document
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Generate context
    context = await get_spiro_context_for_document(doc)
    
    return {
        "document_id": doc_id,
        "vendor_raw": doc.get("vendor_raw"),
        "vendor_normalized": doc.get("vendor_normalized"),
        "spiro_context": context.to_dict()
    }


@spiro_router.post("/context/test")
async def test_spiro_context(
    vendor_name: str = Query(None),
    vendor_email: str = Query(None),
    email_from: str = Query(None)
):
    """
    Test SpiroContext generation with arbitrary input.
    
    Useful for testing matching logic without a real document.
    """
    from services.spiro.spiro_context import SpiroContextGenerator, get_spiro_db
    
    spiro_db = get_spiro_db()
    if not spiro_db:
        raise HTTPException(status_code=500, detail="Spiro database not initialized")
    
    generator = SpiroContextGenerator(spiro_db)
    context = await generator.generate_context(
        vendor_name=vendor_name,
        vendor_email=vendor_email,
        email_from=email_from
    )
    
    return {
        "input": {
            "vendor_name": vendor_name,
            "vendor_email": vendor_email,
            "email_from": email_from
        },
        "spiro_context": context.to_dict()
    }
