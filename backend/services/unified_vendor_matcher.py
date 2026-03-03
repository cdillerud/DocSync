"""
Unified Vendor Intelligence Service

Aggregates vendor matching from ALL available sources:
1. Spiro CRM - 11,700+ companies
2. Business Central - Vendor master data
3. SharePoint Documents - Historical document patterns
4. MongoDB Document History - Previously matched vendors

Uses intelligent fuzzy matching and caching for performance.
"""

import logging
import re
import os
import httpx
from typing import Dict, Any, Optional, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from difflib import SequenceMatcher
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class UnifiedVendorMatcher:
    """
    Unified vendor matching across all data sources.
    Priority order:
    1. Document history (fastest - previously matched)
    2. Spiro CRM (large dataset)
    3. Business Central (authoritative for AP)
    4. SharePoint patterns (historical documents)
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._cache = {}
        self._bc_token = None
        self._bc_token_expires = None
        
        # BC Production credentials from env
        self.bc_tenant_id = os.environ.get("BC_PROD_TENANT_ID", "")
        self.bc_environment = os.environ.get("BC_PROD_ENVIRONMENT", "Production")
        self.bc_client_id = os.environ.get("BC_PROD_CLIENT_ID", "")
        self.bc_client_secret = os.environ.get("BC_PROD_CLIENT_SECRET", "")
        self.bc_company_id = None
        
        # SharePoint credentials
        self.graph_client_id = os.environ.get("GRAPH_CLIENT_ID", "")
        self.graph_client_secret = os.environ.get("GRAPH_CLIENT_SECRET", "")
        self.graph_tenant_id = os.environ.get("GRAPH_TENANT_ID", "")
    
    async def match_vendor(
        self,
        vendor_name: str,
        min_score: float = 0.7,
        use_all_sources: bool = True
    ) -> Dict[str, Any]:
        """
        Match a vendor name using all available sources.
        
        Returns comprehensive match result with source attribution.
        """
        if not vendor_name:
            return self._empty_result("no_input")
        
        vendor_normalized = self._normalize_name(vendor_name)
        
        # Check cache
        cache_key = f"{vendor_normalized}:{min_score}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached["from_cache"] = True
            return cached
        
        result = {
            "input": vendor_name,
            "normalized": vendor_normalized,
            "matched": False,
            "best_match": None,
            "score": 0.0,
            "source": None,
            "is_freight_carrier": False,
            "sources_checked": [],
            "all_matches": [],
            "from_cache": False,
            "matched_at": datetime.now(timezone.utc).isoformat()
        }
        
        # ============================================================
        # SOURCE 1: Document History (previously matched vendors)
        # ============================================================
        doc_match = await self._match_from_document_history(vendor_name, vendor_normalized)
        result["sources_checked"].append("document_history")
        
        if doc_match and doc_match.get("score", 0) >= min_score:
            result["all_matches"].append({"source": "document_history", **doc_match})
            if doc_match["score"] > result["score"]:
                result["best_match"] = doc_match
                result["score"] = doc_match["score"]
                result["source"] = "document_history"
                result["matched"] = True
        
        # ============================================================
        # SOURCE 2: Spiro CRM
        # ============================================================
        if use_all_sources:
            spiro_match = await self._match_from_spiro(vendor_name, vendor_normalized, min_score)
            result["sources_checked"].append("spiro_crm")
            
            if spiro_match and spiro_match.get("score", 0) >= min_score:
                result["all_matches"].append({"source": "spiro_crm", **spiro_match})
                if spiro_match["score"] > result["score"]:
                    result["best_match"] = spiro_match
                    result["score"] = spiro_match["score"]
                    result["source"] = "spiro_crm"
                    result["matched"] = True
                    result["is_freight_carrier"] = spiro_match.get("is_freight", False)
        
        # ============================================================
        # SOURCE 3: Business Central Vendors
        # ============================================================
        if use_all_sources and self.bc_client_id:
            bc_match = await self._match_from_bc(vendor_name, vendor_normalized)
            result["sources_checked"].append("business_central")
            
            if bc_match and bc_match.get("score", 0) >= min_score:
                result["all_matches"].append({"source": "business_central", **bc_match})
                # BC is authoritative - prefer if score is close
                if bc_match["score"] >= result["score"] - 0.1:
                    result["best_match"] = bc_match
                    result["score"] = bc_match["score"]
                    result["source"] = "business_central"
                    result["matched"] = True
                    result["bc_vendor_number"] = bc_match.get("vendor_number")
                    result["bc_vendor_id"] = bc_match.get("vendor_id")
        
        # ============================================================
        # SOURCE 4: SharePoint Document Patterns
        # ============================================================
        if use_all_sources and not result["matched"]:
            sp_match = await self._match_from_sharepoint_patterns(vendor_name, vendor_normalized)
            result["sources_checked"].append("sharepoint_patterns")
            
            if sp_match and sp_match.get("score", 0) >= min_score:
                result["all_matches"].append({"source": "sharepoint_patterns", **sp_match})
                if sp_match["score"] > result["score"]:
                    result["best_match"] = sp_match
                    result["score"] = sp_match["score"]
                    result["source"] = "sharepoint_patterns"
                    result["matched"] = True
        
        # Determine if freight carrier
        if result["matched"] and not result["is_freight_carrier"]:
            result["is_freight_carrier"] = self._is_freight_name(
                result["best_match"].get("name", "") if result["best_match"] else vendor_name
            )
        
        # Cache result
        self._cache[cache_key] = result
        
        # Store successful match for future lookups
        if result["matched"]:
            await self._store_vendor_match(vendor_name, result)
        
        return result
    
    async def _match_from_document_history(
        self, 
        vendor_name: str, 
        vendor_normalized: str
    ) -> Optional[Dict]:
        """Check document history for previously matched vendors."""
        
        # Look for exact matches first
        doc = await self.db.hub_documents.find_one(
            {
                "$or": [
                    {"vendor_canonical": {"$regex": f"^{re.escape(vendor_name)}$", "$options": "i"}},
                    {"extracted_fields.vendor": {"$regex": f"^{re.escape(vendor_name)}$", "$options": "i"}}
                ],
                "bc_vendor_number": {"$exists": True, "$ne": None}
            },
            {"_id": 0, "vendor_canonical": 1, "bc_vendor_number": 1, "bc_vendor_id": 1}
        )
        
        if doc:
            return {
                "name": doc.get("vendor_canonical"),
                "vendor_number": doc.get("bc_vendor_number"),
                "vendor_id": doc.get("bc_vendor_id"),
                "score": 1.0,
                "method": "document_history_exact"
            }
        
        # Check vendor matches collection
        match_doc = await self.db.vendor_matches.find_one(
            {"input_normalized": vendor_normalized},
            {"_id": 0}
        )
        
        if match_doc:
            return {
                "name": match_doc.get("matched_name"),
                "vendor_number": match_doc.get("bc_vendor_number"),
                "vendor_id": match_doc.get("bc_vendor_id"),
                "score": match_doc.get("score", 0.9),
                "method": "vendor_matches_cache",
                "is_freight": match_doc.get("is_freight", False)
            }
        
        return None
    
    async def _match_from_spiro(
        self, 
        vendor_name: str, 
        vendor_normalized: str,
        min_score: float
    ) -> Optional[Dict]:
        """Match against Spiro CRM companies."""
        
        # Try exact normalized match
        company = await self.db.spiro_companies.find_one(
            {"name_normalized": vendor_normalized},
            {"_id": 0, "name": 1, "spiro_id": 1, "account_number": 1, "industry": 1}
        )
        
        if company:
            is_freight = self._is_freight_name(company.get("name", "")) or \
                        "freight" in (company.get("industry") or "").lower()
            return {
                "name": company.get("name"),
                "spiro_id": company.get("spiro_id"),
                "account_number": company.get("account_number"),
                "score": 1.0,
                "method": "spiro_exact",
                "is_freight": is_freight
            }
        
        # Fuzzy search
        first_word = vendor_name.split()[0] if vendor_name else ""
        if len(first_word) >= 3:
            candidates = await self.db.spiro_companies.find(
                {"name": {"$regex": f"^{re.escape(first_word)}", "$options": "i"}},
                {"_id": 0, "name": 1, "spiro_id": 1, "account_number": 1, "industry": 1}
            ).limit(20).to_list(20)
            
            best = None
            best_score = 0.0
            
            for c in candidates:
                score = self._calculate_similarity(vendor_name, c.get("name", ""))
                if score > best_score and score >= min_score:
                    best_score = score
                    best = c
            
            if best:
                is_freight = self._is_freight_name(best.get("name", "")) or \
                            "freight" in (best.get("industry") or "").lower()
                return {
                    "name": best.get("name"),
                    "spiro_id": best.get("spiro_id"),
                    "account_number": best.get("account_number"),
                    "score": best_score,
                    "method": "spiro_fuzzy",
                    "is_freight": is_freight
                }
        
        return None
    
    async def _match_from_bc(
        self, 
        vendor_name: str, 
        vendor_normalized: str
    ) -> Optional[Dict]:
        """Match against Business Central vendors."""
        
        try:
            token = await self._get_bc_token()
            if not token:
                return None
            
            company_id = await self._get_bc_company_id(token)
            if not company_id:
                return None
            
            async with httpx.AsyncClient(timeout=30) as client:
                # Try vendor number match first
                resp = await client.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{self.bc_tenant_id}/{self.bc_environment}/api/v2.0/companies({company_id})/vendors",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"number eq '{vendor_name}'"}
                )
                
                if resp.status_code == 200:
                    vendors = resp.json().get("value", [])
                    if vendors:
                        v = vendors[0]
                        return {
                            "name": v.get("displayName"),
                            "vendor_number": v.get("number"),
                            "vendor_id": v.get("id"),
                            "score": 1.0,
                            "method": "bc_vendor_number"
                        }
                
                # Try display name search
                first_word = vendor_name.split()[0] if vendor_name else ""
                if len(first_word) >= 3:
                    resp = await client.get(
                        f"https://api.businesscentral.dynamics.com/v2.0/{self.bc_tenant_id}/{self.bc_environment}/api/v2.0/companies({company_id})/vendors",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"contains(tolower(displayName), '{first_word.lower()}')"}
                    )
                    
                    if resp.status_code == 200:
                        vendors = resp.json().get("value", [])
                        
                        best = None
                        best_score = 0.0
                        
                        for v in vendors:
                            score = self._calculate_similarity(vendor_name, v.get("displayName", ""))
                            if score > best_score:
                                best_score = score
                                best = v
                        
                        if best and best_score >= 0.6:
                            return {
                                "name": best.get("displayName"),
                                "vendor_number": best.get("number"),
                                "vendor_id": best.get("id"),
                                "score": best_score,
                                "method": "bc_display_name"
                            }
        
        except Exception as e:
            logger.warning("BC vendor lookup error: %s", str(e))
        
        return None
    
    async def _match_from_sharepoint_patterns(
        self, 
        vendor_name: str, 
        vendor_normalized: str
    ) -> Optional[Dict]:
        """
        Match against SharePoint document patterns.
        Looks at previously processed documents stored in SharePoint.
        """
        
        # Check documents that were successfully uploaded to SharePoint
        docs = await self.db.hub_documents.find(
            {
                "sharepoint_item_id": {"$exists": True, "$ne": None},
                "vendor_canonical": {"$exists": True, "$ne": None}
            },
            {"_id": 0, "vendor_canonical": 1, "file_name": 1, "sharepoint_folder_path": 1}
        ).limit(100).to_list(100)
        
        # Find similar vendor names
        best = None
        best_score = 0.0
        
        for doc in docs:
            canonical = doc.get("vendor_canonical", "")
            if canonical:
                score = self._calculate_similarity(vendor_name, canonical)
                if score > best_score and score >= 0.7:
                    best_score = score
                    best = doc
        
        if best:
            return {
                "name": best.get("vendor_canonical"),
                "folder_path": best.get("sharepoint_folder_path"),
                "score": best_score,
                "method": "sharepoint_pattern"
            }
        
        return None
    
    async def _store_vendor_match(self, vendor_name: str, result: Dict):
        """Store successful match for future lookups."""
        try:
            await self.db.vendor_matches.update_one(
                {"input_normalized": self._normalize_name(vendor_name)},
                {"$set": {
                    "input_original": vendor_name,
                    "input_normalized": self._normalize_name(vendor_name),
                    "matched_name": result.get("best_match", {}).get("name"),
                    "bc_vendor_number": result.get("bc_vendor_number"),
                    "bc_vendor_id": result.get("bc_vendor_id"),
                    "score": result.get("score"),
                    "source": result.get("source"),
                    "is_freight": result.get("is_freight_carrier"),
                    "updated_at": datetime.now(timezone.utc)
                }},
                upsert=True
            )
        except Exception as e:
            logger.warning("Failed to store vendor match: %s", str(e))
    
    async def _get_bc_token(self) -> Optional[str]:
        """Get BC OAuth token with caching."""
        
        now = datetime.now(timezone.utc)
        if self._bc_token and self._bc_token_expires and self._bc_token_expires > now:
            return self._bc_token
        
        if not self.bc_client_id or not self.bc_client_secret:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{self.bc_tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": self.bc_client_id,
                        "client_secret": self.bc_client_secret,
                        "scope": "https://api.businesscentral.dynamics.com/.default",
                        "grant_type": "client_credentials"
                    }
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    self._bc_token = data.get("access_token")
                    # Token usually valid for 1 hour, refresh at 50 min
                    from datetime import timedelta
                    self._bc_token_expires = now + timedelta(minutes=50)
                    return self._bc_token
        
        except Exception as e:
            logger.warning("BC token error: %s", str(e))
        
        return None
    
    async def _get_bc_company_id(self, token: str) -> Optional[str]:
        """Get BC company ID."""
        
        if self.bc_company_id:
            return self.bc_company_id
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{self.bc_tenant_id}/{self.bc_environment}/api/v2.0/companies",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if resp.status_code == 200:
                    companies = resp.json().get("value", [])
                    if companies:
                        self.bc_company_id = companies[0].get("id")
                        return self.bc_company_id
        
        except Exception as e:
            logger.warning("BC company lookup error: %s", str(e))
        
        return None
    
    def _normalize_name(self, name: str) -> str:
        """Normalize company name for matching."""
        if not name:
            return ""
        
        normalized = name.lower().strip()
        
        # Remove common suffixes
        for suffix in [" inc", " inc.", " llc", " corp", " corp.", " corporation", 
                      " co", " co.", " company", " ltd", " ltd.", " lp", " lp."]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        
        # Remove special characters
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between strings."""
        if not s1 or not s2:
            return 0.0
        
        n1 = self._normalize_name(s1)
        n2 = self._normalize_name(s2)
        
        return SequenceMatcher(None, n1, n2).ratio()
    
    def _is_freight_name(self, name: str) -> bool:
        """Check if name suggests freight carrier."""
        name_lower = name.lower()
        freight_keywords = [
            "freight", "transport", "trucking", "logistics", "carrier",
            "shipping", "express", "delivery", "ltl", "truckload",
            "moving", "hauling", "drayage"
        ]
        return any(kw in name_lower for kw in freight_keywords)
    
    def _empty_result(self, reason: str) -> Dict:
        """Return empty result."""
        return {
            "input": None,
            "normalized": None,
            "matched": False,
            "best_match": None,
            "score": 0.0,
            "source": None,
            "is_freight_carrier": False,
            "sources_checked": [],
            "all_matches": [],
            "reason": reason
        }


# Global instance
_unified_matcher: Optional[UnifiedVendorMatcher] = None


def get_unified_vendor_matcher(db: AsyncIOMotorDatabase) -> UnifiedVendorMatcher:
    """Get or create unified vendor matcher."""
    global _unified_matcher
    if _unified_matcher is None:
        _unified_matcher = UnifiedVendorMatcher(db)
    return _unified_matcher


async def match_vendor_unified(
    db: AsyncIOMotorDatabase,
    vendor_name: str,
    min_score: float = 0.7
) -> Dict[str, Any]:
    """
    Match vendor using all available sources.
    
    Convenience function for use throughout the application.
    """
    matcher = get_unified_vendor_matcher(db)
    return await matcher.match_vendor(vendor_name, min_score)
