"""Reclassification sweep — run updated heuristics against all existing documents.

Run directly:
  docker exec -it gpi-backend python3 -c "
  import asyncio, os, sys
  sys.path.insert(0, 'backend')
  from scripts.reclassify_sweep import run_sweep
  asyncio.run(run_sweep())
  "
"""

import asyncio
import logging
import re
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")

# Invoice indicators — if a doc has 2+ of these, it's an AP_Invoice
_INVOICE_INDICATORS = re.compile(
    r'(invoice\s*#|invoice\s+number|balance\s+due|terms\s*:\s*net\s+\d|'
    r'please\s+remit|amount\s+due|payment\s+terms|remit\s+to|pay\s+this\s+amount|'
    r'remittance|total\s+due|due\s+date)',
    re.IGNORECASE,
)

# Packing list indicators
_PACKING_INDICATORS = re.compile(
    r'(packing\s+list|packing\s+slip|pick\s+list|pick\s+qty|lot\s+number)',
    re.IGNORECASE,
)

# Warehouse receipt indicators
_WR_INDICATORS = re.compile(
    r'(warehouse\s+receipt|non[- ]negotiable\s+warehouse|stored\s+in\s+warehouse)',
    re.IGNORECASE,
)


def _get_doc_text(doc: dict) -> str:
    """Get all searchable text from a document."""
    parts = []
    parts.append(doc.get("file_name", ""))
    
    ef = doc.get("extracted_fields") or {}
    for k, v in ef.items():
        if isinstance(v, str):
            parts.append(v)
    
    nf = doc.get("normalized_fields") or {}
    for k, v in nf.items():
        if isinstance(v, str):
            parts.append(v)
    
    ai = doc.get("ai_extraction") or {}
    for k, v in ai.items():
        if isinstance(v, str):
            parts.append(v)
    
    parts.append(doc.get("raw_text", "") or "")
    parts.append(doc.get("extracted_text", "") or "")
    
    return " ".join(parts)


def _detect_correct_type(doc: dict) -> tuple:
    """Detect what the document type SHOULD be based on heuristics.
    
    Returns (new_type, reason) or (None, None) if current type seems correct.
    """
    current_type = doc.get("document_type") or ""
    text = _get_doc_text(doc)
    file_name = (doc.get("file_name") or "").lower()
    
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    
    # --- Check 1: Freight_Document that's actually an AP_Invoice ---
    if current_type == "Freight_Document":
        invoice_hits = _INVOICE_INDICATORS.findall(text)
        if len(invoice_hits) >= 2:
            return "AP_Invoice", f"Freight_Document with {len(invoice_hits)} invoice indicators: {invoice_hits[:3]}"
        
        # Also check if extracted fields have invoice-like data
        has_invoice_num = bool(ef.get("invoice_number") or nf.get("invoice_number"))
        has_amount = bool(ef.get("amount") or nf.get("amount") or ef.get("total_amount"))
        has_due_date = bool(ef.get("due_date") or ef.get("payment_terms"))
        if has_invoice_num and has_amount:
            return "AP_Invoice", f"Freight_Document with invoice_number + amount in extracted fields"
    
    # --- Check 2: Sales_Order that's actually a Shipping_Document (packing list) ---
    if current_type in ("Sales_Order", "Order_Confirmation", "Unknown_Document"):
        if _PACKING_INDICATORS.search(file_name) or _PACKING_INDICATORS.search(text):
            return "Shipping_Document", f"{current_type} with packing list indicators in text/filename"
    
    # --- Check 3: Sales_Order that's actually a Warehouse_Receipt ---
    if current_type in ("Sales_Order", "Unknown_Document"):
        if _WR_INDICATORS.search(text):
            return "Warehouse_Receipt", f"{current_type} with warehouse receipt indicators"
    
    # --- Check 4: Unknown_Document that's actually an AP_Invoice ---
    if current_type in ("Unknown_Document", "Unknown", "OTHER", "Other"):
        invoice_hits = _INVOICE_INDICATORS.findall(text)
        if len(invoice_hits) >= 2:
            return "AP_Invoice", f"Unknown with {len(invoice_hits)} invoice indicators"
    
    # --- Check 5: Any type with strong invoice indicators that isn't AP_Invoice ---
    if current_type not in ("AP_Invoice", "AR_Invoice", "Remittance", "Credit_Memo"):
        invoice_hits = _INVOICE_INDICATORS.findall(text)
        if len(invoice_hits) >= 3:
            # Very strong invoice signal on a non-invoice type
            return "AP_Invoice", f"{current_type} with {len(invoice_hits)} strong invoice indicators"
    
    return None, None


async def run_sweep(dry_run: bool = False):
    """Run the reclassification sweep across all documents."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    total = await db.hub_documents.count_documents({})
    print(f"Scanning {total} documents for misclassifications...")
    
    changes = []
    scanned = 0
    
    cursor = db.hub_documents.find(
        {},
        {"_id": 0, "id": 1, "document_type": 1, "file_name": 1, "extracted_fields": 1,
         "normalized_fields": 1, "ai_extraction": 1, "raw_text": 1, "extracted_text": 1,
         "vendor_canonical": 1, "vendor_raw": 1}
    )
    
    async for doc in cursor:
        scanned += 1
        new_type, reason = _detect_correct_type(doc)
        
        if new_type:
            old_type = doc.get("document_type", "?")
            changes.append({
                "doc_id": doc["id"],
                "file_name": doc.get("file_name", "?"),
                "old_type": old_type,
                "new_type": new_type,
                "reason": reason,
            })
            
            if not dry_run:
                now = datetime.now(timezone.utc).isoformat()
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "document_type": new_type,
                        "classification_override": new_type,
                        "reclassified_at": now,
                        "reclassified_reason": reason,
                        "reclassified_from": old_type,
                        "updated_utc": now,
                    }}
                )
                
                # Record the correction for AI learning
                from services.classification_feedback_service import init_classification_feedback, record_correction
                init_classification_feedback(db)
                await record_correction(
                    doc_id=doc["id"],
                    original_type=old_type,
                    corrected_type=new_type,
                    corrected_by="reclassification_sweep",
                    doc_context={
                        "file_name": doc.get("file_name", ""),
                        "vendor_raw": doc.get("vendor_raw", ""),
                        "vendor_canonical": doc.get("vendor_canonical", ""),
                        "text_snippet": reason,
                    },
                )
    
    # Print summary
    print(f"\nScanned: {scanned}")
    print(f"Reclassified: {len(changes)}")
    
    if changes:
        # Group by change type
        from collections import Counter
        change_types = Counter(f"{c['old_type']} → {c['new_type']}" for c in changes)
        print(f"\nChanges by type:")
        for ct, count in change_types.most_common():
            print(f"  {ct}: {count}")
        
        print(f"\nDetails:")
        for c in changes:
            prefix = "[DRY RUN] " if dry_run else "[UPDATED] "
            print(f"  {prefix}{c['file_name'][:50]:50s} {c['old_type']:25s} → {c['new_type']:25s} ({c['reason'][:60]})")
    else:
        print("No misclassifications found.")
    
    client.close()
    return {"scanned": scanned, "reclassified": len(changes), "changes": changes}


if __name__ == "__main__":
    asyncio.run(run_sweep())
