"""
GPI Document Hub — Template Value Injection Service

Merges a posting template's learned structure (GL, tax, UOM, line type,
description pattern) with live extracted values (reference number, amount,
line splits) from the current document.

Runs after extraction and before template-driven draft creation.
"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.providers.base_provider import LLMProviderError

logger = logging.getLogger(__name__)

# Fields that are ALWAYS sourced from the template — never overridden
STRUCTURAL_FIELDS = {"lineType", "lineObjectNumber", "taxCode", "uom",
                     "unitOfMeasureCode", "item_or_account"}


@dataclass
class InjectionResult:
    lines: List[Dict[str, Any]]
    injections_applied: int
    injections_skipped: int
    confidence: float
    audit_trail: List[Dict[str, Any]]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def inject_extracted_values(
    template_lines: List[Dict[str, Any]],
    extraction_result: Dict[str, Any],
    vendor_id: str,
    document_context: Dict[str, Any],
) -> InjectionResult:
    """
    Merge template structure with live extracted values.

    Priority rules per field:
      1. Amount (unit_price, netAmount, unitCost): extracted > template
         Multi-line splits preserve template ratios applied to extracted total.
      2. Description/reference: LLM extracts actual ref from raw text,
         falls back to template pattern.
      3. GL, tax, UOM, line type: always template.
      4. Quantity: extracted if present, else template default.
    """
    audit: List[Dict[str, Any]] = []
    applied = 0
    skipped = 0

    if not template_lines:
        return InjectionResult(
            lines=[], injections_applied=0, injections_skipped=0,
            confidence=1.0, audit_trail=[], error="No template lines provided",
        )

    # --- Extraction data ---
    ext_total = _safe_float(extraction_result.get("total_amount")
                            or extraction_result.get("amount_float")
                            or extraction_result.get("amount"))
    ext_invoice_number = (extraction_result.get("invoice_number")
                          or extraction_result.get("invoice_number_clean") or "")
    ext_po_number = extraction_result.get("po_number") or ""
    ext_quantity = _safe_float(extraction_result.get("quantity"))
    ext_bol = extraction_result.get("bol_number") or ""
    raw_text = (document_context.get("raw_text_snippet") or "")[:500]

    # --- Compute template total for ratio-based splits ---
    template_total = sum(_safe_float(ln.get("netAmount") or ln.get("unitCost") or 0)
                         for ln in template_lines)

    # --- Try to extract a reference via LLM if raw text is available ---
    llm_ref = ""
    if raw_text:
        llm_ref = await _extract_reference_via_llm(raw_text, vendor_id, ext_invoice_number)

    # Pick best available reference
    best_ref = llm_ref or ext_bol or ext_po_number or ext_invoice_number

    # --- Inject into each line ---
    merged_lines: List[Dict[str, Any]] = []

    for line_idx, tpl in enumerate(template_lines):
        merged = dict(tpl)  # shallow copy
        line_audit: List[Dict[str, Any]] = []

        # -- Structural fields: always template --
        for sf in STRUCTURAL_FIELDS:
            if sf in tpl:
                line_audit.append({"field": sf, "source": "template",
                                   "value": tpl[sf]})

        # -- Amount fields --
        tpl_amount = _safe_float(tpl.get("netAmount") or tpl.get("unitCost") or 0)

        if ext_total and ext_total > 0:
            if len(template_lines) == 1:
                # Single line: entire extracted total
                merged["unitCost"] = ext_total
                merged["netAmount"] = ext_total
                line_audit.append({"field": "amount", "source": "extracted",
                                   "value": ext_total, "note": "single line, full total"})
                applied += 1
            elif template_total > 0:
                # Multi-line: preserve template ratio
                ratio = tpl_amount / template_total if template_total else 0
                line_amount = round(ext_total * ratio, 2)
                merged["unitCost"] = line_amount
                merged["netAmount"] = line_amount
                line_audit.append({"field": "amount", "source": "extracted",
                                   "value": line_amount,
                                   "note": f"ratio={ratio:.4f} of extracted total {ext_total}"})
                applied += 1
            else:
                # Template total is 0 — distribute evenly
                share = round(ext_total / len(template_lines), 2)
                merged["unitCost"] = share
                merged["netAmount"] = share
                line_audit.append({"field": "amount", "source": "extracted",
                                   "value": share, "note": "even split (template total=0)"})
                applied += 1
        else:
            line_audit.append({"field": "amount", "source": "template",
                               "value": tpl_amount, "note": "no extracted total"})
            skipped += 1

        # -- Quantity --
        if ext_quantity and ext_quantity > 0:
            merged["quantity"] = ext_quantity
            line_audit.append({"field": "quantity", "source": "extracted",
                               "value": ext_quantity})
            applied += 1
        else:
            line_audit.append({"field": "quantity", "source": "template",
                               "value": tpl.get("quantity", 1)})
            # Don't count quantity as skipped if template default of 1 is fine

        # -- Description / reference --
        tpl_desc = tpl.get("description", "")
        slot_type = tpl.get("slot_type", "")
        is_zero_cost = tpl.get("is_zero_cost", False)
        is_structural_desc = is_zero_cost or slot_type in ("surcharge", "structural_constant", "structural_zero")

        if is_structural_desc:
            # Structural descriptions stay as-is
            line_audit.append({"field": "description", "source": "template",
                               "value": tpl_desc, "note": "structural line"})
        elif best_ref:
            # Inject actual reference into description pattern
            new_desc = _inject_ref_into_description(tpl_desc, best_ref)
            merged["description"] = new_desc
            ref_source = "llm" if (llm_ref and best_ref == llm_ref) else "extracted"
            line_audit.append({"field": "description", "source": ref_source,
                               "value": new_desc,
                               "note": f"ref '{best_ref}' injected into pattern"})
            applied += 1
        else:
            line_audit.append({"field": "description", "source": "template",
                               "value": tpl_desc, "note": "no ref available"})
            skipped += 1

        # -- Tax code: always template --
        tc = tpl.get("taxCode", "")
        line_audit.append({"field": "tax_code", "source": "template", "value": tc})

        # -- UOM: always template --
        uom = tpl.get("uom", "") or tpl.get("unitOfMeasureCode", "")
        line_audit.append({"field": "uom", "source": "template", "value": uom})

        audit.append({"line_index": line_idx, "item": tpl.get("lineObjectNumber", ""),
                       "fields": line_audit})
        merged_lines.append(merged)

    # -- Fix rounding on multi-line splits so total matches exactly --
    if ext_total and ext_total > 0 and len(merged_lines) > 1:
        merged_sum = sum(_safe_float(ln.get("netAmount", 0)) for ln in merged_lines)
        diff = round(ext_total - merged_sum, 2)
        if abs(diff) > 0 and abs(diff) <= 1.0:
            # Apply rounding adjustment to the largest line
            biggest_idx = max(range(len(merged_lines)),
                              key=lambda i: _safe_float(merged_lines[i].get("netAmount", 0)))
            merged_lines[biggest_idx]["netAmount"] = round(
                _safe_float(merged_lines[biggest_idx]["netAmount"]) + diff, 2)
            merged_lines[biggest_idx]["unitCost"] = merged_lines[biggest_idx]["netAmount"]

    total = applied + skipped
    confidence = (applied / total) if total > 0 else 1.0

    return InjectionResult(
        lines=merged_lines,
        injections_applied=applied,
        injections_skipped=skipped,
        confidence=round(confidence, 4),
        audit_trail=audit,
    )


# ─── Helpers ───

def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _inject_ref_into_description(template_desc: str, ref: str) -> str:
    """Replace the reference portion of a template description pattern."""
    import re
    # "Freight 52260" → "Freight {ref}"
    m = re.match(r'^((?:FREIGHT|FRT|Freight)\s+)\S+', template_desc, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{ref}"
    # "PO 12345" → "PO {ref}"
    m = re.match(r'^(PO[#\s]+)\S+', template_desc, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{ref}"
    # Pure numeric ref "52260" → replace entirely
    if re.match(r'^\d{4,}$', template_desc.strip()):
        return ref
    # Contains a numeric token → replace it
    if re.search(r'\d{4,}', template_desc):
        return re.sub(r'\d{4,}', ref, template_desc, count=1)
    # No pattern found — prepend ref
    return ref


async def _extract_reference_via_llm(raw_text: str, vendor_id: str, invoice_number: str) -> str:
    """
    Ask the LLM to extract the actual reference/BOL/PO number from raw document text.
    Returns just the reference string, empty on failure.
    """
    try:
        from services.llm_router import get_provider
        provider = get_provider("extraction")
    except LLMProviderError:
        return ""

    system_prompt = (
        "You are a document reference extractor. Given raw text from an invoice, "
        "extract the primary reference number (BOL, PO, order number, or shipment reference) "
        "that should appear in the posting line description. "
        "Return ONLY the reference number/string, nothing else. "
        "If no reference is found, return empty string."
    )
    user_prompt = (
        f"Vendor: {vendor_id}\n"
        f"Invoice number: {invoice_number}\n"
        f"Document text (first 500 chars):\n{raw_text}\n\n"
        f"Extract the primary reference number:"
    )

    try:
        result = await provider.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            session_id=f"ref_extract_{vendor_id}_{invoice_number[:20]}",
            expect_json=False,
        )
        # Clean up — remove quotes, whitespace, "none" answers
        ref = result.strip().strip('"').strip("'").strip()
        if ref.lower() in ("", "none", "n/a", "null", "not found", "empty"):
            return ""
        return ref
    except Exception as exc:
        logger.debug("[TemplateInjector] LLM ref extraction failed: %s", exc)
        return ""
