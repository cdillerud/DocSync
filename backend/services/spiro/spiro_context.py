"""
GPI Document Hub - Spiro Context Generator

Generates SpiroContext for documents by matching document metadata
against synced Spiro data (companies, contacts, opportunities).

The SpiroContext is used by the AI document validation pipeline to:
- Improve vendor/customer identification accuracy
- Validate that documents belong to known accounts
- Provide ISR/OSR context for routing decisions

Matching strategies:
1. Company name similarity (normalized, fuzzy)
2. Email domain matching
3. Address proximity
4. Phone number matching
5. Alias/variation matching
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
from motor.motor_asyncio import AsyncIOMotorDatabase

from .spiro_client import is_spiro_enabled
from .spiro_sync import get_spiro_db

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Matching thresholds
NAME_MATCH_THRESHOLD = 0.75  # Minimum similarity for name matching
FUZZY_MATCH_THRESHOLD = 0.65  # Lower threshold for fuzzy matches
MAX_MATCHES_PER_TYPE = 5  # Maximum matches to return per entity type

# Feature flag for including Spiro context in validation
SPIRO_CONTEXT_ENABLED = os.environ.get("SPIRO_CONTEXT_ENABLED", "true").lower() in ("true", "1", "yes")


# =============================================================================
# TEXT NORMALIZATION
# =============================================================================

def normalize_company_name(name: str) -> str:
    """
    Normalize company name for comparison.
    
    Removes common suffixes, punctuation, and normalizes whitespace.
    """
    if not name:
        return ""
    
    # Convert to uppercase
    normalized = name.upper().strip()
    
    # Remove common company suffixes
    suffixes = [
        r'\s+INC\.?$', r'\s+LLC\.?$', r'\s+LTD\.?$', r'\s+CO\.?$',
        r'\s+CORP\.?$', r'\s+CORPORATION$', r'\s+COMPANY$',
        r'\s+INCORPORATED$', r'\s+LIMITED$', r',\s*INC\.?$',
        r',\s*LLC\.?$', r',\s*LTD\.?$'
    ]
    
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)
    
    # Remove punctuation except spaces
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    
    # Normalize whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized


def extract_email_domain(email: str) -> Optional[str]:
    """Extract domain from email address."""
    if not email or '@' not in email:
        return None
    return email.split('@')[-1].lower().strip()


def normalize_phone(phone: str) -> str:
    """Normalize phone number to digits only."""
    if not phone:
        return ""
    return re.sub(r'[^\d]', '', phone)


def calculate_name_similarity(name1: str, name2: str) -> float:
    """
    Calculate similarity between two company names.
    
    Returns a score between 0.0 and 1.0.
    """
    if not name1 or not name2:
        return 0.0
    
    norm1 = normalize_company_name(name1)
    norm2 = normalize_company_name(name2)
    
    if not norm1 or not norm2:
        return 0.0
    
    # Exact match after normalization
    if norm1 == norm2:
        return 1.0
    
    # Use sequence matcher for fuzzy matching
    return SequenceMatcher(None, norm1, norm2).ratio()


# =============================================================================
# SPIRO CONTEXT DATA STRUCTURES
# =============================================================================

class SpiroMatch:
    """Represents a match between document data and a Spiro record."""
    
    def __init__(
        self,
        spiro_id: str,
        entity_type: str,  # "company", "contact", "opportunity"
        name: str,
        match_score: float,
        match_reasons: List[str],
        data: Dict[str, Any]
    ):
        self.spiro_id = spiro_id
        self.entity_type = entity_type
        self.name = name
        self.match_score = match_score
        self.match_reasons = match_reasons
        self.data = data
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "spiro_id": self.spiro_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "match_score": round(self.match_score, 3),
            "match_reasons": self.match_reasons,
            "assigned_isr": self.data.get("assigned_isr"),
            "assigned_osr": self.data.get("assigned_osr"),
            "owner": self.data.get("owner"),
            "status": self.data.get("status"),
            "city": self.data.get("city"),
            "state": self.data.get("state")
        }


class SpiroContext:
    """
    Context object containing Spiro matches and confidence signals
    for a document.
    """
    
    def __init__(self):
        self.matched_companies: List[SpiroMatch] = []
        self.matched_contacts: List[SpiroMatch] = []
        self.matched_opportunities: List[SpiroMatch] = []
        self.confidence_signals: Dict[str, Any] = {}
        self.generated_at: str = datetime.now(timezone.utc).isoformat()
        self.enabled: bool = True
        self.error: Optional[str] = None
    
    def add_company_match(self, match: SpiroMatch):
        self.matched_companies.append(match)
        self.matched_companies.sort(key=lambda m: m.match_score, reverse=True)
        self.matched_companies = self.matched_companies[:MAX_MATCHES_PER_TYPE]
    
    def add_contact_match(self, match: SpiroMatch):
        self.matched_contacts.append(match)
        self.matched_contacts.sort(key=lambda m: m.match_score, reverse=True)
        self.matched_contacts = self.matched_contacts[:MAX_MATCHES_PER_TYPE]
    
    def add_opportunity_match(self, match: SpiroMatch):
        self.matched_opportunities.append(match)
        self.matched_opportunities.sort(key=lambda m: m.match_score, reverse=True)
        self.matched_opportunities = self.matched_opportunities[:MAX_MATCHES_PER_TYPE]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched_companies": [m.to_dict() for m in self.matched_companies],
            "matched_contacts": [m.to_dict() for m in self.matched_contacts],
            "matched_opportunities": [m.to_dict() for m in self.matched_opportunities],
            "confidence_signals": self.confidence_signals,
            "generated_at": self.generated_at,
            "enabled": self.enabled,
            "error": self.error,
            "has_matches": bool(self.matched_companies or self.matched_contacts or self.matched_opportunities),
            "best_company_match": self.matched_companies[0].to_dict() if self.matched_companies else None,
            "best_contact_match": self.matched_contacts[0].to_dict() if self.matched_contacts else None
        }


# =============================================================================
# SPIRO CONTEXT GENERATOR
# =============================================================================

class SpiroContextGenerator:
    """
    Generates SpiroContext for documents by matching against Spiro data.
    
    Usage:
        generator = SpiroContextGenerator(db)
        context = await generator.generate_context(doc_metadata)
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
    
    async def _find_matching_companies(
        self,
        vendor_name: Optional[str] = None,
        email_domain: Optional[str] = None,
        phone: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> List[SpiroMatch]:
        """
        Find Spiro companies matching the given criteria.
        """
        matches = []
        
        # If we have a vendor name, search by name similarity
        if vendor_name:
            normalized_vendor = normalize_company_name(vendor_name)
            
            # Get all companies and score them
            # In production with large datasets, use text indexes
            cursor = self.db.spiro_companies.find({}, {"_id": 0})
            companies = await cursor.to_list(length=1000)
            
            for company in companies:
                match_reasons = []
                score = 0.0
                
                # Name similarity
                company_normalized = company.get("name_normalized", "")
                name_score = calculate_name_similarity(vendor_name, company.get("name", ""))
                
                if name_score >= NAME_MATCH_THRESHOLD:
                    score = max(score, name_score)
                    match_reasons.append(f"name_similarity:{name_score:.2f}")
                elif name_score >= FUZZY_MATCH_THRESHOLD:
                    score = max(score, name_score * 0.8)  # Reduce score for fuzzy matches
                    match_reasons.append(f"fuzzy_name:{name_score:.2f}")
                
                # Email domain match
                if email_domain and company.get("email_domain"):
                    if email_domain.lower() == company["email_domain"].lower():
                        score = max(score, 0.9)
                        match_reasons.append("email_domain_match")
                
                # Phone match
                if phone and company.get("phone"):
                    norm_phone = normalize_phone(phone)
                    company_phone = normalize_phone(company["phone"])
                    if norm_phone and company_phone and norm_phone[-10:] == company_phone[-10:]:
                        score = max(score, 0.85)
                        match_reasons.append("phone_match")
                
                # Location match (boost score if location matches)
                if city and company.get("city"):
                    if city.upper() == company["city"].upper():
                        score += 0.1
                        match_reasons.append("city_match")
                
                if state and company.get("state"):
                    if state.upper() == company["state"].upper():
                        score += 0.05
                        match_reasons.append("state_match")
                
                # Only include if we have a meaningful match
                if score >= FUZZY_MATCH_THRESHOLD and match_reasons:
                    matches.append(SpiroMatch(
                        spiro_id=company["spiro_id"],
                        entity_type="company",
                        name=company.get("name", ""),
                        match_score=min(score, 1.0),
                        match_reasons=match_reasons,
                        data=company
                    ))
        
        # Sort by score and limit
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:MAX_MATCHES_PER_TYPE]
    
    async def _find_matching_contacts(
        self,
        email: Optional[str] = None,
        email_domain: Optional[str] = None,
        name: Optional[str] = None,
        company_ids: Optional[List[str]] = None
    ) -> List[SpiroMatch]:
        """
        Find Spiro contacts matching the given criteria.
        """
        matches = []
        query = {}
        
        # Build query
        if company_ids:
            query["company_id"] = {"$in": company_ids}
        
        if email:
            query["email"] = {"$regex": re.escape(email), "$options": "i"}
        elif email_domain:
            query["email_domain"] = email_domain.lower()
        
        cursor = self.db.spiro_contacts.find(query, {"_id": 0}).limit(50)
        contacts = await cursor.to_list(length=50)
        
        for contact in contacts:
            match_reasons = []
            score = 0.0
            
            # Email exact match
            if email and contact.get("email"):
                if email.lower() == contact["email"].lower():
                    score = 1.0
                    match_reasons.append("email_exact_match")
            
            # Email domain match
            if email_domain and contact.get("email_domain"):
                if email_domain.lower() == contact["email_domain"].lower():
                    score = max(score, 0.7)
                    match_reasons.append("email_domain_match")
            
            # Company association
            if company_ids and contact.get("company_id") in company_ids:
                score = max(score, 0.6)
                match_reasons.append("company_association")
            
            if score > 0 and match_reasons:
                matches.append(SpiroMatch(
                    spiro_id=contact["spiro_id"],
                    entity_type="contact",
                    name=contact.get("full_name", ""),
                    match_score=score,
                    match_reasons=match_reasons,
                    data=contact
                ))
        
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:MAX_MATCHES_PER_TYPE]
    
    async def _find_matching_opportunities(
        self,
        company_ids: Optional[List[str]] = None,
        contact_ids: Optional[List[str]] = None
    ) -> List[SpiroMatch]:
        """
        Find Spiro opportunities related to matched companies/contacts.
        """
        if not company_ids and not contact_ids:
            return []
        
        matches = []
        query = {"$or": []}
        
        if company_ids:
            query["$or"].append({"company_id": {"$in": company_ids}})
        if contact_ids:
            query["$or"].append({"contact_id": {"$in": contact_ids}})
        
        if not query["$or"]:
            return []
        
        cursor = self.db.spiro_opportunities.find(query, {"_id": 0}).limit(20)
        opportunities = await cursor.to_list(length=20)
        
        for opp in opportunities:
            match_reasons = []
            score = 0.5  # Base score for related opportunities
            
            if company_ids and opp.get("company_id") in company_ids:
                score += 0.3
                match_reasons.append("company_related")
            
            if contact_ids and opp.get("contact_id") in contact_ids:
                score += 0.2
                match_reasons.append("contact_related")
            
            matches.append(SpiroMatch(
                spiro_id=opp["spiro_id"],
                entity_type="opportunity",
                name=opp.get("name", ""),
                match_score=min(score, 1.0),
                match_reasons=match_reasons,
                data=opp
            ))
        
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:MAX_MATCHES_PER_TYPE]
    
    async def generate_context(
        self,
        vendor_name: Optional[str] = None,
        vendor_email: Optional[str] = None,
        vendor_phone: Optional[str] = None,
        vendor_city: Optional[str] = None,
        vendor_state: Optional[str] = None,
        email_from: Optional[str] = None,
        **kwargs  # Accept additional fields for future expansion
    ) -> SpiroContext:
        """
        Generate SpiroContext for a document.
        
        Args:
            vendor_name: Vendor/company name from document
            vendor_email: Vendor email address
            vendor_phone: Vendor phone number
            vendor_city: Vendor city
            vendor_state: Vendor state
            email_from: Email sender address (for email-ingested docs)
        
        Returns:
            SpiroContext with matches and confidence signals
        """
        context = SpiroContext()
        
        # Check if Spiro is enabled
        if not is_spiro_enabled():
            context.enabled = False
            context.error = "Spiro integration disabled"
            return context
        
        if not SPIRO_CONTEXT_ENABLED:
            context.enabled = False
            context.error = "Spiro context generation disabled"
            return context
        
        try:
            # Extract email domain
            email_domain = None
            if vendor_email:
                email_domain = extract_email_domain(vendor_email)
            elif email_from:
                email_domain = extract_email_domain(email_from)
            
            # Find matching companies
            company_matches = await self._find_matching_companies(
                vendor_name=vendor_name,
                email_domain=email_domain,
                phone=vendor_phone,
                city=vendor_city,
                state=vendor_state
            )
            
            for match in company_matches:
                context.add_company_match(match)
            
            # Get company IDs for related lookups
            matched_company_ids = [m.spiro_id for m in company_matches]
            
            # Find matching contacts
            contact_matches = await self._find_matching_contacts(
                email=vendor_email or email_from,
                email_domain=email_domain,
                company_ids=matched_company_ids
            )
            
            for match in contact_matches:
                context.add_contact_match(match)
            
            # Get contact IDs
            matched_contact_ids = [m.spiro_id for m in contact_matches]
            
            # Find related opportunities
            opp_matches = await self._find_matching_opportunities(
                company_ids=matched_company_ids,
                contact_ids=matched_contact_ids
            )
            
            for match in opp_matches:
                context.add_opportunity_match(match)
            
            # Build confidence signals
            context.confidence_signals = {
                "has_company_match": bool(company_matches),
                "has_contact_match": bool(contact_matches),
                "has_opportunity_match": bool(opp_matches),
                "best_company_score": company_matches[0].match_score if company_matches else 0.0,
                "best_contact_score": contact_matches[0].match_score if contact_matches else 0.0,
                "name_match_used": any("name" in r for m in company_matches for r in m.match_reasons),
                "email_domain_match": any("email_domain" in r for m in (company_matches + contact_matches) for r in m.match_reasons),
                "phone_match": any("phone" in r for m in company_matches for r in m.match_reasons),
                "location_match": any("city" in r or "state" in r for m in company_matches for r in m.match_reasons),
                # ISR/OSR from best match
                "matched_isr": company_matches[0].data.get("assigned_isr") if company_matches else None,
                "matched_osr": company_matches[0].data.get("assigned_osr") if company_matches else None,
                "matched_owner": company_matches[0].data.get("owner") if company_matches else None
            }
            
            logger.debug(
                "Generated SpiroContext: %d companies, %d contacts, %d opportunities",
                len(context.matched_companies),
                len(context.matched_contacts),
                len(context.matched_opportunities)
            )
            
        except Exception as e:
            logger.error("Error generating SpiroContext: %s", str(e))
            context.error = str(e)
        
        return context


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def get_spiro_context_for_document(doc_metadata: Dict[str, Any]) -> SpiroContext:
    """
    Generate SpiroContext for a document.
    
    Extracts relevant fields from document metadata and generates context.
    
    Usage:
        from services.spiro import get_spiro_context_for_document
        
        context = await get_spiro_context_for_document({
            "vendor_raw": "Tumalo Creek Transportation",
            "vendor_email": "billing@tumalo.com",
            "email_from": "invoices@tumalo.com"
        })
    """
    db = get_spiro_db()
    if db is None:
        context = SpiroContext()
        context.enabled = False
        context.error = "Database not initialized"
        return context
    
    generator = SpiroContextGenerator(db)
    
    # Extract fields from document metadata
    extracted_fields = doc_metadata.get("extracted_fields", {})
    
    return await generator.generate_context(
        vendor_name=doc_metadata.get("vendor_raw") or doc_metadata.get("vendor_normalized") or extracted_fields.get("vendor"),
        vendor_email=extracted_fields.get("vendor_email"),
        vendor_phone=extracted_fields.get("vendor_phone"),
        vendor_city=extracted_fields.get("vendor_city") or extracted_fields.get("city"),
        vendor_state=extracted_fields.get("vendor_state") or extracted_fields.get("state"),
        email_from=doc_metadata.get("email_from")
    )
