"""
GPI Document Hub - Spiro Data Sync Service

Handles synchronization of Spiro data (contacts, companies, opportunities)
to local MongoDB collections for fast lookup during document validation.

Collections created:
- spiro_contacts: Contact records with ISR/OSR, status, location
- spiro_companies: Company/account records
- spiro_opportunities: Opportunities/projects
- spiro_sync_status: Sync metadata and timestamps

Sync behavior:
- Incremental sync based on updated_at timestamp when available
- Full sync on first run or when forced
- Idempotent upsert operations
- Rate-limit-friendly pagination
"""

import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from .spiro_client import SpiroClient, get_spiro_client, is_spiro_enabled

logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE REFERENCE (set during app startup)
# =============================================================================

_db: Optional[AsyncIOMotorDatabase] = None

def set_spiro_db(db: AsyncIOMotorDatabase):
    """Set the database reference for Spiro sync operations."""
    global _db
    _db = db
    logger.info("Spiro sync service initialized with database")

def get_spiro_db() -> Optional[AsyncIOMotorDatabase]:
    """Get the database reference."""
    return _db


# =============================================================================
# DATA TRANSFORMATION
# =============================================================================

def transform_contact(raw_contact: Dict) -> Dict:
    """
    Transform Spiro JSON:API contact to our storage format.
    
    Input format (JSON:API):
    {
        "id": "12345",
        "type": "contacts",
        "attributes": {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "555-1234",
            "title": "Purchasing Manager",
            "custom": {
                "assigned_isr": "...",
                "status": "Active",
                ...
            },
            "created_at": "...",
            "updated_at": "..."
        },
        "relationships": {
            "company": {"data": {"id": "999", "type": "companies"}}
        }
    }
    """
    attrs = raw_contact.get("attributes", {})
    custom = attrs.get("custom", {})
    relationships = raw_contact.get("relationships", {})
    
    # Extract company ID from relationship
    company_rel = relationships.get("company", {}).get("data", {})
    company_id = company_rel.get("id") if company_rel else None
    
    return {
        "spiro_id": raw_contact.get("id"),
        "first_name": attrs.get("first_name", ""),
        "last_name": attrs.get("last_name", ""),
        "full_name": f"{attrs.get('first_name', '')} {attrs.get('last_name', '')}".strip(),
        "email": attrs.get("email"),
        "phone": attrs.get("phone"),
        "mobile": attrs.get("mobile"),
        "title": attrs.get("title"),
        "company_id": company_id,
        # Custom fields
        "assigned_isr": custom.get("assigned_isr"),
        "assigned_osr": custom.get("assigned_osr"),
        "owner": custom.get("owner") or attrs.get("owner"),
        "status": custom.get("status") or attrs.get("status"),
        # Location
        "address": custom.get("address") or attrs.get("address"),
        "city": custom.get("city") or attrs.get("city"),
        "state": custom.get("state") or attrs.get("state"),
        "country": custom.get("country") or attrs.get("country"),
        "postal_code": custom.get("postal_code") or attrs.get("postal_code"),
        # Metadata
        "created_at": attrs.get("created_at"),
        "updated_at": attrs.get("updated_at"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        # Email domain for matching
        "email_domain": attrs.get("email", "").split("@")[-1].lower() if attrs.get("email") else None
    }


def transform_company(raw_company: Dict) -> Dict:
    """
    Transform Spiro JSON:API company to our storage format.
    """
    attrs = raw_company.get("attributes", {})
    custom = attrs.get("custom", {})
    
    return {
        "spiro_id": raw_company.get("id"),
        "name": attrs.get("name", ""),
        "name_normalized": (attrs.get("name", "") or "").upper().strip(),
        "website": attrs.get("website"),
        "phone": attrs.get("phone"),
        "industry": attrs.get("industry") or custom.get("industry"),
        # Owner/assignment
        "owner": custom.get("owner") or attrs.get("owner"),
        "assigned_isr": custom.get("assigned_isr"),
        "assigned_osr": custom.get("assigned_osr"),
        "status": custom.get("status") or attrs.get("status"),
        # Location
        "address": custom.get("address") or attrs.get("address"),
        "city": custom.get("city") or attrs.get("city"),
        "state": custom.get("state") or attrs.get("state"),
        "country": custom.get("country") or attrs.get("country"),
        "postal_code": custom.get("postal_code") or attrs.get("postal_code"),
        # Financial context
        "annual_revenue": custom.get("annual_revenue"),
        "employee_count": custom.get("employee_count"),
        # Metadata
        "created_at": attrs.get("created_at"),
        "updated_at": attrs.get("updated_at"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        # Domain for email matching
        "email_domain": (attrs.get("website", "") or "").replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower() if attrs.get("website") else None
    }


def transform_opportunity(raw_opp: Dict) -> Dict:
    """
    Transform Spiro JSON:API opportunity to our storage format.
    """
    attrs = raw_opp.get("attributes", {})
    custom = attrs.get("custom", {})
    relationships = raw_opp.get("relationships", {})
    
    # Extract company and contact IDs
    company_rel = relationships.get("company", {}).get("data", {})
    company_id = company_rel.get("id") if company_rel else None
    
    contact_rel = relationships.get("contact", {}).get("data", {})
    contact_id = contact_rel.get("id") if contact_rel else None
    
    return {
        "spiro_id": raw_opp.get("id"),
        "name": attrs.get("name", ""),
        "company_id": company_id,
        "contact_id": contact_id,
        # Stage/status
        "stage": attrs.get("stage") or custom.get("stage"),
        "status": attrs.get("status") or custom.get("status"),
        "probability": attrs.get("probability"),
        # Financial
        "value": attrs.get("value") or custom.get("value"),
        "currency": attrs.get("currency", "USD"),
        "close_date": attrs.get("close_date") or custom.get("close_date"),
        # Owner
        "owner": custom.get("owner") or attrs.get("owner"),
        # Metadata
        "created_at": attrs.get("created_at"),
        "updated_at": attrs.get("updated_at"),
        "synced_at": datetime.now(timezone.utc).isoformat()
    }


# =============================================================================
# SYNC SERVICE
# =============================================================================

class SpiroSyncService:
    """
    Service for synchronizing Spiro data to local MongoDB.
    
    Supports incremental and full sync modes.
    """
    
    def __init__(self, db: AsyncIOMotorDatabase, client: Optional[SpiroClient] = None):
        self.db = db
        self.client = client or get_spiro_client()
    
    async def _get_last_sync_time(self, entity_type: str) -> Optional[datetime]:
        """Get the last successful sync timestamp for an entity type."""
        status = await self.db.spiro_sync_status.find_one({"entity_type": entity_type})
        if status and status.get("last_sync_success"):
            try:
                return datetime.fromisoformat(status["last_sync_success"].replace('Z', '+00:00'))
            except Exception:
                pass
        return None
    
    async def _update_sync_status(self, entity_type: str, success: bool, records_synced: int, error: str = None):
        """Update sync status for an entity type."""
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "entity_type": entity_type,
            "last_sync_attempt": now,
            "records_synced": records_synced,
            "updated_at": now
        }
        
        if success:
            update["last_sync_success"] = now
            update["last_error"] = None
        else:
            update["last_error"] = error
        
        await self.db.spiro_sync_status.update_one(
            {"entity_type": entity_type},
            {"$set": update},
            upsert=True
        )
    
    async def sync_contacts(self, force_full: bool = False) -> Dict[str, Any]:
        """
        Sync contacts from Spiro to local collection.
        
        Args:
            force_full: If True, ignore last sync time and sync all records
            
        Returns:
            Dict with sync results
        """
        if not is_spiro_enabled():
            return {"success": False, "error": "Spiro integration disabled", "records": 0}
        
        if not self.client.is_configured():
            return {"success": False, "error": "Spiro not configured", "records": 0}
        
        logger.info("Starting Spiro contacts sync (force_full=%s)", force_full)
        
        # Get last sync time for incremental
        updated_since = None if force_full else await self._get_last_sync_time("contacts")
        
        total_synced = 0
        total_pages = 0
        page = 1
        
        try:
            while True:
                response = await self.client.list_contacts(page=page, per_page=100, updated_since=updated_since)
                
                if not response:
                    logger.error("Failed to fetch contacts page %d", page)
                    break
                
                data = response.get("data", [])
                if not data:
                    break
                
                # Transform and upsert
                for raw_contact in data:
                    contact = transform_contact(raw_contact)
                    await self.db.spiro_contacts.update_one(
                        {"spiro_id": contact["spiro_id"]},
                        {"$set": contact},
                        upsert=True
                    )
                    total_synced += 1
                
                total_pages += 1
                
                # Check pagination
                meta = response.get("meta", {}).get("pagination", {})
                current_page = meta.get("current_page", page)
                total_pages_available = meta.get("total_pages", 1)
                
                if current_page >= total_pages_available:
                    break
                
                page += 1
                
                # Rate limiting courtesy
                await asyncio.sleep(0.1)
            
            await self._update_sync_status("contacts", True, total_synced)
            logger.info("Spiro contacts sync complete: %d records synced", total_synced)
            
            return {
                "success": True,
                "entity_type": "contacts",
                "records": total_synced,
                "pages": total_pages,
                "incremental": updated_since is not None
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Spiro contacts sync error: %s", error_msg)
            await self._update_sync_status("contacts", False, total_synced, error_msg)
            return {"success": False, "error": error_msg, "records": total_synced}
    
    async def sync_companies(self, force_full: bool = False) -> Dict[str, Any]:
        """Sync companies from Spiro to local collection."""
        if not is_spiro_enabled():
            return {"success": False, "error": "Spiro integration disabled", "records": 0}
        
        if not self.client.is_configured():
            return {"success": False, "error": "Spiro not configured", "records": 0}
        
        logger.info("Starting Spiro companies sync (force_full=%s)", force_full)
        
        updated_since = None if force_full else await self._get_last_sync_time("companies")
        
        total_synced = 0
        total_pages = 0
        page = 1
        
        try:
            while True:
                response = await self.client.list_companies(page=page, per_page=100, updated_since=updated_since)
                
                if not response:
                    logger.error("Failed to fetch companies page %d", page)
                    break
                
                data = response.get("data", [])
                if not data:
                    break
                
                for raw_company in data:
                    company = transform_company(raw_company)
                    await self.db.spiro_companies.update_one(
                        {"spiro_id": company["spiro_id"]},
                        {"$set": company},
                        upsert=True
                    )
                    total_synced += 1
                
                total_pages += 1
                
                meta = response.get("meta", {}).get("pagination", {})
                current_page = meta.get("current_page", page)
                total_pages_available = meta.get("total_pages", 1)
                
                if current_page >= total_pages_available:
                    break
                
                page += 1
                await asyncio.sleep(0.1)
            
            await self._update_sync_status("companies", True, total_synced)
            logger.info("Spiro companies sync complete: %d records synced", total_synced)
            
            return {
                "success": True,
                "entity_type": "companies",
                "records": total_synced,
                "pages": total_pages,
                "incremental": updated_since is not None
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Spiro companies sync error: %s", error_msg)
            await self._update_sync_status("companies", False, total_synced, error_msg)
            return {"success": False, "error": error_msg, "records": total_synced}
    
    async def sync_opportunities(self, force_full: bool = False) -> Dict[str, Any]:
        """Sync opportunities from Spiro to local collection."""
        if not is_spiro_enabled():
            return {"success": False, "error": "Spiro integration disabled", "records": 0}
        
        if not self.client.is_configured():
            return {"success": False, "error": "Spiro not configured", "records": 0}
        
        logger.info("Starting Spiro opportunities sync (force_full=%s)", force_full)
        
        updated_since = None if force_full else await self._get_last_sync_time("opportunities")
        
        total_synced = 0
        total_pages = 0
        page = 1
        
        try:
            while True:
                response = await self.client.list_opportunities(page=page, per_page=100, updated_since=updated_since)
                
                if not response:
                    logger.error("Failed to fetch opportunities page %d", page)
                    break
                
                data = response.get("data", [])
                if not data:
                    break
                
                for raw_opp in data:
                    opp = transform_opportunity(raw_opp)
                    await self.db.spiro_opportunities.update_one(
                        {"spiro_id": opp["spiro_id"]},
                        {"$set": opp},
                        upsert=True
                    )
                    total_synced += 1
                
                total_pages += 1
                
                meta = response.get("meta", {}).get("pagination", {})
                current_page = meta.get("current_page", page)
                total_pages_available = meta.get("total_pages", 1)
                
                if current_page >= total_pages_available:
                    break
                
                page += 1
                await asyncio.sleep(0.1)
            
            await self._update_sync_status("opportunities", True, total_synced)
            logger.info("Spiro opportunities sync complete: %d records synced", total_synced)
            
            return {
                "success": True,
                "entity_type": "opportunities",
                "records": total_synced,
                "pages": total_pages,
                "incremental": updated_since is not None
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Spiro opportunities sync error: %s", error_msg)
            await self._update_sync_status("opportunities", False, total_synced, error_msg)
            return {"success": False, "error": error_msg, "records": total_synced}
    
    async def sync_all(self, force_full: bool = False) -> Dict[str, Any]:
        """
        Sync all Spiro entities.
        
        Returns combined results from all sync operations.
        """
        logger.info("Starting full Spiro sync (force_full=%s)", force_full)
        
        results = {
            "contacts": await self.sync_contacts(force_full),
            "companies": await self.sync_companies(force_full),
            "opportunities": await self.sync_opportunities(force_full)
        }
        
        total_records = sum(r.get("records", 0) for r in results.values())
        all_success = all(r.get("success", False) for r in results.values())
        
        return {
            "success": all_success,
            "total_records": total_records,
            "results": results,
            "synced_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status for all entity types."""
        cursor = self.db.spiro_sync_status.find({}, {"_id": 0})
        statuses = await cursor.to_list(length=100)
        
        # Get collection counts
        contacts_count = await self.db.spiro_contacts.count_documents({})
        companies_count = await self.db.spiro_companies.count_documents({})
        opportunities_count = await self.db.spiro_opportunities.count_documents({})
        
        return {
            "enabled": is_spiro_enabled(),
            "configured": get_spiro_client().is_configured(),
            "sync_statuses": {s["entity_type"]: s for s in statuses},
            "collection_counts": {
                "contacts": contacts_count,
                "companies": companies_count,
                "opportunities": opportunities_count
            }
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def sync_all_spiro_data(force_full: bool = False) -> Dict[str, Any]:
    """
    Convenience function to sync all Spiro data.
    
    Usage:
        from services.spiro import sync_all_spiro_data
        result = await sync_all_spiro_data()
    """
    db = get_spiro_db()
    if not db:
        return {"success": False, "error": "Database not initialized"}
    
    service = SpiroSyncService(db)
    return await service.sync_all(force_full)


async def sync_spiro_contacts(force_full: bool = False) -> Dict[str, Any]:
    """Convenience function to sync just contacts."""
    db = get_spiro_db()
    if not db:
        return {"success": False, "error": "Database not initialized"}
    
    service = SpiroSyncService(db)
    return await service.sync_contacts(force_full)


async def get_spiro_sync_status() -> Dict[str, Any]:
    """Get current sync status."""
    db = get_spiro_db()
    if db is None:
        return {"enabled": False, "error": "Database not initialized"}
    
    service = SpiroSyncService(db)
    return await service.get_sync_status()
