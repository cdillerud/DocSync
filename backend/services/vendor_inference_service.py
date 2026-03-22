"""
GPI Document Hub - Vendor Inference Service

Fallback vendor resolution strategies for documents where the primary
AI extraction failed to identify a vendor:

1. Filename-based vendor extraction (parse known vendor names from filenames)
2. Invoice number range mapping (known vendor-specific number sequences)
3. Document source patterns (email sender, scanner source)
4. Sibling document inference (other docs in same batch with known vendors)

Used both in the classification pipeline (post-extraction fallback) and
in the Intake Benchmark auto-populate flow.
"""

import re
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known vendor patterns in filenames
# ---------------------------------------------------------------------------

# Exact or partial vendor names that appear in GPI document filenames.
# Format: (compiled_regex, canonical_vendor_name)
FILENAME_VENDOR_PATTERNS = [
    # Direct vendor name in filename
    (re.compile(r'GAMER\s*PACKAGING', re.IGNORECASE), "GAMER PACKAGING INC"),
    (re.compile(r'Valley\s*Distribut', re.IGNORECASE), "VALLEY DISTRIBUTING AND STORAGE COMPANY"),
    (re.compile(r'Gamer\s*Ship', re.IGNORECASE), "GAMER PACKAGING INC"),
    (re.compile(r'GamerPackaging', re.IGNORECASE), "GAMER PACKAGING INC"),
    (re.compile(r'\bBuske\b', re.IGNORECASE), "BUSKE LOGISTICS"),
    (re.compile(r'\bCiticargo\b', re.IGNORECASE), "CITICARGO & STORAGE"),
    (re.compile(r'\bTumaloc\b', re.IGNORECASE), "TUMALOC"),
    (re.compile(r'\bFevisa\b', re.IGNORECASE), "FEVISA INDUSTRIAL S.A. DE C.V."),
    (re.compile(r'\bVitrocrisa\b', re.IGNORECASE), "VITROCRISA S.A. DE C.V."),
    (re.compile(r'\bEnvases\b', re.IGNORECASE), "ENVASES UNIVERSALES DE MEXICO"),
    (re.compile(r'\bSMC\s*Worldwide\b', re.IGNORECASE), "SMC WORLDWIDE LLC"),
    (re.compile(r'\bBall\s*Corp', re.IGNORECASE), "BALL CORPORATION"),
    (re.compile(r'\bAnchor\s*Glass\b', re.IGNORECASE), "ANCHOR GLASS CONTAINER"),
    (re.compile(r'Owens[\s-]*Illinois|O[\s-]*I\b', re.IGNORECASE), "OWENS-ILLINOIS INC"),
    (re.compile(r'\bXPO\b', re.IGNORECASE), "XPO LOGISTICS"),
    (re.compile(r'\bSAIA\b', re.IGNORECASE), "SAIA INC"),
    (re.compile(r'\bProgressive\s*Logistics\b', re.IGNORECASE), "PROGRESSIVE LOGISTICS"),
    (re.compile(r'\bAir\s*Menzies\b', re.IGNORECASE), "AIR MENZIES INTERNATIONAL (USA) INC"),
    (re.compile(r'\bSC\s*Warehouses?\b', re.IGNORECASE), "SC WAREHOUSES, LLC"),
    (re.compile(r'\bCargo\s*Modules?\b', re.IGNORECASE), "CARGO MODULES LLC"),
    (re.compile(r'\bGuala\b', re.IGNORECASE), "GUALA CLOSURES NORTH AMERICA"),
    (re.compile(r'\bRotondo\b', re.IGNORECASE), "ROTONDO"),
    (re.compile(r'\bGroupwa\b', re.IGNORECASE), "GROUPWA"),
    (re.compile(r'\bMidwest\s*Industrial\b', re.IGNORECASE), "MIDWEST INDUSTRIAL SUPPLY LLC"),
    (re.compile(r'\bParkway\s*Plastics\b', re.IGNORECASE), "PARKWAY PLASTICS INC"),
    (re.compile(r'\bFort\s*Dearborn\b', re.IGNORECASE), "FORT DEARBORN COMPANY"),
    (re.compile(r'\bArkansas\s*Glass\b', re.IGNORECASE), "ARKANSAS GLASS CONTAINER CORP"),
    (re.compile(r'\bLone\s*Star\b', re.IGNORECASE), "LONE STAR INTEGRATED DISTRIBUTION, LLC"),
    (re.compile(r'\bProtiviti\b', re.IGNORECASE), "PROTIVITI INC"),
    (re.compile(r'H\s*&\s*P\s*Import', re.IGNORECASE), "H&P IMPORTS LLC"),
    # Email sender patterns
    (re.compile(r'copier@buske\.com', re.IGNORECASE), "BUSKE LOGISTICS"),
]


# ---------------------------------------------------------------------------
# Invoice number range patterns
# ---------------------------------------------------------------------------

# Known vendor-specific invoice number ranges or prefixes.
# These are learned from production document patterns.
INVOICE_NUMBER_VENDOR_MAP = [
    # TUMALOC: 7-digit invoices in 0300000-0309999 range
    (re.compile(r'^030[0-9]{4}\.pdf$'), "TUMALOC"),
    # CCF_ prefix = SMC Worldwide
    (re.compile(r'^CCF_\d+\.pdf$', re.IGNORECASE), "SMC WORLDWIDE LLC"),
    # INUS prefix = Air Menzies International
    (re.compile(r'^INUS\d+\.pdf$', re.IGNORECASE), "AIR MENZIES INTERNATIONAL (USA) INC"),
    # GR prefix = GROUPWA
    (re.compile(r'^GR\d{5,}\.pdf$', re.IGNORECASE), "GROUPWA"),
]


# ---------------------------------------------------------------------------
# Document number patterns that link to known sources
# ---------------------------------------------------------------------------

# Warehouse receipt / BOL number patterns tied to specific companies
DOCUMENT_NUMBER_PATTERNS = [
    # R66xx series = CITICARGO warehouse receipts
    (re.compile(r'R6[56789]\d{2}', re.IGNORECASE), "CITICARGO & STORAGE"),
    # W117xxx series = could be multiple warehouses, but commonly CITICARGO
    (re.compile(r'W117\d{3}', re.IGNORECASE), "CITICARGO & STORAGE"),
]


# ---------------------------------------------------------------------------
# Noise file detection
# ---------------------------------------------------------------------------

NOISE_PATTERNS = [
    re.compile(r'^linkedin_\d+x\d+', re.IGNORECASE),
    re.compile(r'^QR[0-9a-f]{8}', re.IGNORECASE),
    re.compile(r'^Outlook-[a-z]+\.png$', re.IGNORECASE),
    re.compile(r'^image\d{3}\.png$', re.IGNORECASE),
    re.compile(r'^ATT\d+\.(png|jpg|gif)$', re.IGNORECASE),
]


def is_noise_file(filename: str) -> bool:
    """Check if a file is likely noise (not a real business document)."""
    for pattern in NOISE_PATTERNS:
        if pattern.search(filename):
            return True
    # Very small image files
    if filename.lower().endswith(('.png', '.jpg', '.gif', '.bmp')) and not any(
        kw in filename.lower() for kw in ('invoice', 'bol', 'receipt', 'scan', 'doc')
    ):
        return True
    return False


def infer_vendor_from_filename(filename: str) -> Optional[str]:
    """
    Try to extract a vendor name from the document filename.
    
    Returns canonical vendor name if found, None otherwise.
    """
    if not filename:
        return None
    
    # Strategy 1: Direct vendor name patterns in filename
    for pattern, vendor in FILENAME_VENDOR_PATTERNS:
        if pattern.search(filename):
            logger.debug("[VendorInfer] Filename match: %s -> %s", filename, vendor)
            return vendor
    
    return None


def infer_vendor_from_invoice_number(filename: str) -> Optional[str]:
    """
    Try to map a document by its invoice number pattern to a known vendor.
    
    Many vendors use consistent invoice number formats.
    """
    if not filename:
        return None
    
    for pattern, vendor in INVOICE_NUMBER_VENDOR_MAP:
        if pattern.match(filename):
            logger.debug("[VendorInfer] Invoice number match: %s -> %s", filename, vendor)
            return vendor
    
    return None


def infer_vendor_from_document_numbers(filename: str) -> Optional[str]:
    """
    Check for known document number patterns (BOL, warehouse receipt, etc.)
    """
    if not filename:
        return None
    
    for pattern, vendor in DOCUMENT_NUMBER_PATTERNS:
        if pattern.search(filename):
            logger.debug("[VendorInfer] Document number match: %s -> %s", filename, vendor)
            return vendor
    
    return None


def infer_vendor(filename: str, extracted_fields: Optional[Dict] = None) -> Tuple[Optional[str], str]:
    """
    Multi-strategy vendor inference.
    
    Returns (vendor_name, method) where method describes how the vendor was inferred.
    Returns (None, "none") if no vendor could be inferred.
    """
    # Skip noise files
    if is_noise_file(filename):
        return None, "noise_file"
    
    # Strategy 1: Filename vendor patterns
    vendor = infer_vendor_from_filename(filename)
    if vendor:
        return vendor, "filename_pattern"
    
    # Strategy 2: Invoice number format
    vendor = infer_vendor_from_invoice_number(filename)
    if vendor:
        return vendor, "invoice_number_range"
    
    # Strategy 3: Document number patterns (BOL, WR numbers)
    vendor = infer_vendor_from_document_numbers(filename)
    if vendor:
        return vendor, "document_number_pattern"
    
    # Strategy 4: If extracted_fields has email_from, try to match
    if extracted_fields:
        email_from = extracted_fields.get("email_from", "") or extracted_fields.get("sender", "")
        if email_from:
            for pattern, vendor in FILENAME_VENDOR_PATTERNS:
                if pattern.search(email_from):
                    return vendor, "email_sender"
    
    return None, "none"


async def infer_vendor_from_siblings(db, filename: str, batch_id: str = None) -> Optional[str]:
    """
    Try to infer vendor from sibling documents in the same batch/email.
    
    If other documents in the same email or upload batch have a known vendor,
    this document likely belongs to the same vendor.
    """
    if not batch_id or not db:
        return None
    
    # Find other docs in the same batch with a resolved vendor
    sibling = await db.hub_documents.find_one(
        {
            "batch_id": batch_id,
            "file_name": {"$ne": filename},
            "vendor_canonical": {"$ne": None, "$exists": True},
        },
        {"_id": 0, "vendor_canonical": 1, "vendor_resolved_name": 1},
    )
    
    if sibling:
        vendor = sibling.get("vendor_resolved_name") or sibling.get("vendor_canonical")
        if vendor:
            logger.info("[VendorInfer] Sibling match for %s -> %s (from batch %s)", filename, vendor, batch_id)
            return vendor
    
    return None
