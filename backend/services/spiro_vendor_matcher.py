"""
Spiro Vendor Matching Service

Uses Spiro CRM data to intelligently match vendor names from documents
to known companies. This eliminates the need for hardcoded vendor aliases.
"""

import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class SpiroVendorMatcher:
    """
    Matches vendor names from documents against Spiro CRM company data.
    Uses fuzzy matching and normalization for intelligent matching.
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._cache = {}  # Simple cache for repeated lookups
        
    async def match_vendor(
        self, 
        vendor_name: str,
        min_score: float = 0.7
    ) -> Tuple[Optional[Dict], float, str]:
        """
        Match a vendor name against Spiro companies.
        
        Args:
            vendor_name: The vendor name extracted from document
            min_score: Minimum similarity score (0-1) to accept match
            
        Returns:
            Tuple of (matched_company, score, match_method)
        """
        if not vendor_name:
            return None, 0.0, "no_input"
        
        vendor_normalized = self._normalize_name(vendor_name)
        
        # Check cache first
        if vendor_normalized in self._cache:
            cached = self._cache[vendor_normalized]
            return cached["company"], cached["score"], cached["method"]
        
        # Strategy 1: Exact normalized name match
        company = await self.db.spiro_companies.find_one(
            {"name_normalized": vendor_normalized},
            {"_id": 0}
        )
        if company:
            self._cache[vendor_normalized] = {"company": company, "score": 1.0, "method": "exact_normalized"}
            return company, 1.0, "exact_normalized"
        
        # Strategy 2: Regex contains match
        first_word = vendor_name.split()[0] if vendor_name else ""
        if len(first_word) >= 3:
            company = await self.db.spiro_companies.find_one(
                {"name": {"$regex": f"^{re.escape(first_word)}", "$options": "i"}},
                {"_id": 0}
            )
            if company:
                score = self._calculate_similarity(vendor_name, company.get("name", ""))
                if score >= min_score:
                    self._cache[vendor_normalized] = {"company": company, "score": score, "method": "prefix_match"}
                    return company, score, "prefix_match"
        
        # Strategy 3: Fuzzy search on top candidates
        candidates = await self.db.spiro_companies.find(
            {"name": {"$regex": re.escape(first_word[:3]) if first_word else "", "$options": "i"}},
            {"_id": 0, "name": 1, "spiro_id": 1, "account_number": 1, "industry": 1, "city": 1, "state": 1}
        ).limit(50).to_list(50)
        
        best_match = None
        best_score = 0.0
        
        for candidate in candidates:
            score = self._calculate_similarity(vendor_name, candidate.get("name", ""))
            if score > best_score and score >= min_score:
                best_score = score
                best_match = candidate
        
        if best_match:
            self._cache[vendor_normalized] = {"company": best_match, "score": best_score, "method": "fuzzy"}
            return best_match, best_score, "fuzzy"
        
        # No match found
        self._cache[vendor_normalized] = {"company": None, "score": 0.0, "method": "no_match"}
        return None, 0.0, "no_match"
    
    async def search_companies(
        self, 
        query: str, 
        limit: int = 10,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Search Spiro companies by name.
        
        Args:
            query: Search query
            limit: Max results to return
            filters: Additional MongoDB filters
            
        Returns:
            List of matching companies
        """
        base_filter = {"name": {"$regex": re.escape(query), "$options": "i"}}
        if filters:
            base_filter.update(filters)
        
        companies = await self.db.spiro_companies.find(
            base_filter,
            {"_id": 0}
        ).limit(limit).to_list(limit)
        
        # Sort by similarity to query
        companies.sort(
            key=lambda c: self._calculate_similarity(query, c.get("name", "")),
            reverse=True
        )
        
        return companies
    
    async def get_freight_carriers(self) -> List[Dict]:
        """Get all freight/transportation companies from Spiro."""
        return await self.db.spiro_companies.find(
            {"$or": [
                {"name": {"$regex": "freight|transport|trucking|logistics|carrier|shipping", "$options": "i"}},
                {"industry": {"$regex": "freight|transport|logistics|shipping", "$options": "i"}}
            ]},
            {"_id": 0, "name": 1, "spiro_id": 1, "account_number": 1}
        ).to_list(500)
    
    async def is_freight_carrier(self, vendor_name: str) -> Tuple[bool, Optional[Dict]]:
        """
        Check if a vendor is a freight carrier based on Spiro data.
        
        Returns:
            Tuple of (is_freight, matched_company)
        """
        company, score, method = await self.match_vendor(vendor_name)
        
        if company:
            # Check if company name suggests freight
            name = company.get("name", "").lower()
            industry = (company.get("industry") or "").lower()
            
            freight_keywords = ["freight", "transport", "trucking", "logistics", 
                              "carrier", "shipping", "express", "delivery", "ltl"]
            
            is_freight = any(kw in name or kw in industry for kw in freight_keywords)
            return is_freight, company
        
        # Fallback: Check if the input name suggests freight
        vendor_lower = vendor_name.lower()
        is_freight = any(kw in vendor_lower for kw in 
                        ["freight", "transport", "trucking", "logistics", "carrier"])
        return is_freight, None
    
    def _normalize_name(self, name: str) -> str:
        """Normalize a company name for matching."""
        if not name:
            return ""
        
        # Lowercase
        normalized = name.lower().strip()
        
        # Remove common suffixes
        suffixes = [" inc", " inc.", " llc", " corp", " corp.", " corporation", 
                   " co", " co.", " company", " ltd", " ltd."]
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        
        # Remove special characters
        normalized = re.sub(r'[^\w\s]', '', normalized)
        
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity score between two strings."""
        if not s1 or not s2:
            return 0.0
        
        # Normalize both strings
        n1 = self._normalize_name(s1)
        n2 = self._normalize_name(s2)
        
        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, n1, n2).ratio()


# Singleton instance - initialized in server.py
_matcher_instance: Optional[SpiroVendorMatcher] = None


def get_spiro_matcher(db: AsyncIOMotorDatabase) -> SpiroVendorMatcher:
    """Get or create the Spiro vendor matcher instance."""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = SpiroVendorMatcher(db)
    return _matcher_instance


async def match_vendor_with_spiro(
    db: AsyncIOMotorDatabase,
    vendor_name: str,
    min_score: float = 0.7
) -> Dict[str, Any]:
    """
    Convenience function to match a vendor using Spiro data.
    
    Returns dict with:
        - matched: bool
        - company: dict or None
        - score: float
        - method: str
        - is_freight: bool
    """
    matcher = get_spiro_matcher(db)
    
    company, score, method = await matcher.match_vendor(vendor_name, min_score)
    is_freight, _ = await matcher.is_freight_carrier(vendor_name) if company else (False, None)
    
    return {
        "matched": company is not None,
        "company": company,
        "score": score,
        "method": method,
        "is_freight": is_freight,
        "vendor_input": vendor_name
    }
