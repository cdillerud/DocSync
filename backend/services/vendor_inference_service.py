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
    Multi-strategy vendor inference (synchronous — no DB).
    
    Returns (vendor_name, method) where method describes how the vendor was inferred.
    Returns (None, "none") if no vendor could be inferred.
    """
    # Skip noise files
    if is_noise_file(filename):
        return None, "noise_file"
    
    # Check if vendor is "not expected" for this document type
    if is_no_vendor_expected(filename):
        return None, "no_vendor_expected"
    
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


# ---------------------------------------------------------------------------
# "No vendor expected" classification (Option C)
# ---------------------------------------------------------------------------

# Document types/patterns where a vendor is genuinely not present
NO_VENDOR_EXPECTED_PATTERNS = [
    # Internal documents
    re.compile(r'Letter\s+of\s+Authorization', re.IGNORECASE),
    re.compile(r'AR\s+Aging\s+Details', re.IGNORECASE),
    re.compile(r'Page_\d+_\d+\.pdf$', re.IGNORECASE),  # Generic scan pages
    re.compile(r'^W9\b', re.IGNORECASE),  # W-9 tax forms (vendor identity IS the doc)
    re.compile(r'Payment\s+Advice', re.IGNORECASE),  # Remittance/payment docs
    re.compile(r'Remittance', re.IGNORECASE),
]


def is_no_vendor_expected(filename: str) -> bool:
    """Check if a document is a type where vendor extraction is N/A."""
    for pattern in NO_VENDOR_EXPECTED_PATTERNS:
        if pattern.search(filename):
            return True
    return False


# ---------------------------------------------------------------------------
# BC Cross-Reference for BOL/Shipment Numbers (Option A)
# ---------------------------------------------------------------------------

def extract_reference_numbers(filename: str) -> list:
    """
    Extract potential BOL/shipment/order reference numbers from a filename.
    
    Returns a list of (reference, ref_type) tuples.
    """
    refs = []
    stem = re.sub(r'\.[^.]+$', '', filename)  # strip extension
    
    # BOL number pattern: "BOL 111574" or "BOL 1111645"
    bol_match = re.findall(r'BOL\s*(\d{5,})', stem, re.IGNORECASE)
    for m in bol_match:
        refs.append((m, "bol"))
    
    # Shipment reference: S-number like "S174310" or "S8830"
    s_match = re.findall(r'\bS(\d{4,})', stem)
    for m in s_match:
        refs.append((m, "shipment"))
        refs.append(("S" + m, "shipment"))
    
    # WTR (Warehouse Transfer Receipt): "WTR 1010", "WTR1011"
    wtr_match = re.findall(r'WTR\s*(\d{3,})', stem, re.IGNORECASE)
    for m in wtr_match:
        refs.append((m, "wtr"))
        refs.append(("WTR" + m, "wtr"))
    
    # PO reference: "P0023772" or similar
    po_match = re.findall(r'\b(P\d{6,})', stem, re.IGNORECASE)
    for m in po_match:
        refs.append((m, "po"))
    
    # Standalone 6-digit numbers (could be shipment/order numbers)
    # Be selective: only if no other refs found and filename suggests shipping
    if not refs:
        standalone = re.findall(r'\b(\d{6})\b', stem)
        for m in standalone:
            refs.append((m, "standalone"))
    
    # W-numbers: W117543
    w_match = re.findall(r'\b(W\d{5,})', stem, re.IGNORECASE)
    for m in w_match:
        refs.append((m, "warehouse"))
    
    # CN numbers: CN000107C
    cn_match = re.findall(r'\b(CN\d{4,}\w*)', stem, re.IGNORECASE)
    for m in cn_match:
        refs.append((m, "container"))
    
    return refs


async def infer_vendor_from_bc_references(db, filename: str) -> Tuple[Optional[str], str, list]:
    """
    Cross-reference document numbers from filename against BC cache.
    
    Searches bc_reference_cache for posted shipments, sales orders, and
    purchase orders that match reference numbers found in the filename.
    
    Returns (vendor_name, method, matched_refs) or (None, "none", []).
    """
    refs = extract_reference_numbers(filename)
    if not refs:
        return None, "none", []
    
    for ref_value, ref_type in refs:
        normalized = ref_value.strip().upper()
        if not normalized:
            continue
        
        # Search bc_reference_cache for this reference
        query = {
            "$or": [
                {"normalized_document_no": normalized},
                {"bc_document_no": normalized},
                {"bc_external_document_no": normalized},
                {"normalized_external_ref": normalized},
                {"bc_order_number": normalized},
            ]
        }
        
        hit = await db.bc_reference_cache.find_one(query, {"_id": 0})
        
        if hit:
            # Extract vendor info from the BC record
            vendor = (
                hit.get("bc_vendor_name") or hit.get("bc_customer_name")
                or hit.get("bc_sell_to_customer_name") or hit.get("bc_buy_from_vendor_name")
                or ""
            )
            vendor_no = hit.get("bc_vendor_no") or hit.get("bc_customer_no") or ""
            entity_type = hit.get("bc_entity_type", "")
            
            if vendor:
                logger.info(
                    "[VendorInfer:BC] %s -> ref=%s type=%s -> vendor=%s (%s)",
                    filename[:40], normalized, entity_type, vendor, ref_type,
                )
                return vendor, f"bc_cache_{ref_type}", [(ref_value, entity_type, vendor)]
            elif vendor_no:
                logger.info(
                    "[VendorInfer:BC] %s -> ref=%s -> vendor_no=%s (no name)",
                    filename[:40], normalized, vendor_no,
                )
                return vendor_no, f"bc_cache_{ref_type}_no", [(ref_value, entity_type, vendor_no)]
    
    return None, "none", []


async def infer_vendor_async(
    db, filename: str, extracted_fields: Optional[Dict] = None,
    batch_id: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Full async vendor inference including DB-backed strategies.
    
    Tries all synchronous strategies first, then:
    5. BC reference cache cross-reference (BOL/shipment numbers)
    6. Sibling document inference (same batch/email)
    
    Returns (vendor_name, method).
    """
    # Try synchronous strategies first
    vendor, method = infer_vendor(filename, extracted_fields)
    if vendor or method in ("noise_file", "no_vendor_expected"):
        return vendor, method
    
    # Strategy 5: BC reference cache cross-reference
    if db is not None:
        try:
            vendor, method, refs = await infer_vendor_from_bc_references(db, filename)
            if vendor:
                return vendor, method
        except Exception as e:
            logger.debug("[VendorInfer:BC] Error: %s", e)
    
    # Strategy 6: Sibling document inference
    if db is not None and batch_id:
        try:
            vendor = await infer_vendor_from_siblings(db, filename, batch_id)
            if vendor:
                return vendor, "sibling_batch"
        except Exception as e:
            logger.debug("[VendorInfer:Sibling] Error: %s", e)
    
    return None, "none"
