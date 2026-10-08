import re
"""How AP codes each vendor's invoice lines in Production BC, and the
draft lines that follow from it.

Measured 2026-10-07 on the sandbox drafts: freight carriers are one
"FREIGHT" item line in 14-15 of AP's last 15 invoices (R+L, ATS, Celtic,
Quarterback, Priority, TForce) and the Hub drafted them right; product
vendors (Pretium, Triumbari, Massilly) are the PO's own items, which the
vendor-profile builder drafted as PALLET / Z-POP. Receipt lines are the
right source for product invoices, but 31 of 42 drafted PO invoices had
no BC receipt yet: the invoice arrives before the goods are received.

So, per invoice:
* lines from the BC receipt(s) that add up to it (receipt_lines_for);
* else, a vendor AP codes with one code (>= 80% of recent invoices, one
  line) gets one line with that code for the invoice amount;
* else, a product vendor's PO invoice waits for its receipt (ap_stage
  "awaiting_receipt"), re-checked every few hours;
* else the vendor-profile lines, only when their main line is a code AP
  actually uses for this vendor.
Read-only against Production BC; rebuilt by the hourly learning cycle.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RECENT = 15
DOMINANT_SHARE = 0.8


def _main(lines: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    ls = [l for l in lines or [] if l.get("lineObjectNumber")]
    return max(ls, key=lambda l: abs(float(l.get("quantity") or 0) * float(l.get("unitCost") or 0)), default=None)


async def rebuild(db, days: int = 60, max_age_hours: int = 24) -> Dict[str, Any]:
    import httpx
    import services.bc_catalog_sync_service as bc
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    vendors = [v for v in await db.hub_documents.distinct(
        "vendor_canonical", {"created_utc": {"$gte": since}, "mailbox_category": "AP", "document_type": "AP_Invoice"}) if v]
    done = set(await db.vendor_line_coding.distinct("vendor", {"updated_at": {"$gte": fresh}}))
    todo = [v for v in vendors if v not in done]
    if not todo:
        return {"vendors": len(vendors), "rebuilt": 0}
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    async with httpx.AsyncClient(timeout=90) as c:
        for v in todo:
            try:
                r = await c.get(f"{base}/purchaseInvoices", headers={"Authorization": f"Bearer {token}"}, params={
                    "$filter": f"vendorNumber eq '{v}' and status ne 'Draft'", "$orderby": "postingDate desc", "$top": str(RECENT),
                    "$expand": "purchaseInvoiceLines($select=lineType,lineObjectNumber,quantity,unitCost)",
                    "$select": "number,postingDate"})
                if r.status_code != 200:
                    continue
                invs = r.json().get("value", [])
            except Exception as e:
                logger.warning("[LineCoding] %s: %r", v, e)
                continue
            mains, codes, one_line = Counter(), Counter(), 0
            for inv in invs:
                ls = [l for l in inv.get("purchaseInvoiceLines", []) if l.get("lineObjectNumber")]
                one_line += len(ls) == 1
                for l in ls:
                    codes[str(l["lineObjectNumber"]).upper()] += 1
                m = _main(ls)
                if m:
                    mains[(str(m.get("lineType") or "Item"), str(m["lineObjectNumber"]).upper())] += 1
            total = len(invs)
            by_code = Counter()
            for (t, code), k in mains.items():
                by_code[code] += k
            dominant = None
            if total >= 5 and by_code:
                code, k = by_code.most_common(1)[0]
                types = Counter({t: kk for (t, cc), kk in mains.items() if cc == code})
                t = next((x for x, _ in types.most_common() if x in ("Item", "Account")), types.most_common(1)[0][0])
                if k / total >= DOMINANT_SHARE and one_line / total >= DOMINANT_SHARE:
                    dominant = {"lineType": t, "lineObjectNumber": code, "share": round(k / total, 2)}
            await db.vendor_line_coding.update_one({"vendor": v}, {"$set": {
                "vendor": v, "invoices": total, "one_line_share": round(one_line / total, 2) if total else None,
                "main_codes": [{"lineType": t, "code": cc, "n": k} for (t, cc), k in mains.most_common(15)],
                "codes_used": sorted(codes), "dominant": dominant, "updated_at": now}}, upsert=True)
            n += 1
    return {"vendors": len(vendors), "rebuilt": n}


async def coding_for(db, vendor: str) -> Optional[Dict[str, Any]]:
    return await db.vendor_line_coding.find_one({"vendor": str(vendor or "").upper()}, {"_id": 0})


def main_code_known(coding: Optional[Dict[str, Any]], lines: List[Dict[str, Any]]) -> Optional[bool]:
    """Is the main line's code one AP uses as the main line for this vendor? None = no history."""
    if not coding or (coding.get("invoices") or 0) < 5:
        return None
    m = _main(lines)
    if not m:
        return False
    # A code AP uses only on minor lines (PALLET, deposits) is not the main
    # line of this vendor's invoices: Pretium / Triumbari drafted as PALLET.
    return str(m["lineObjectNumber"]).upper() in {c["code"] for c in coding.get("main_codes") or []}


_FREIGHT_CODES = {"FREIGHT", "WHSEFRT", "DRAYAGE"}
# Accessorials AP enters as their own line on a carrier invoice (replay
# 2026-10-08: Tumalo DETENTION, ATS FRTTONU).
_ACCESSORIALS = [(re.compile(r"\bDETENTION\b", re.I), "DETENTION"),
                 (re.compile(r"\bTONU\b|TRUCK\s+ORDERED\s+NOT\s+USED", re.I), "FRTTONU")]
# A port container move (ISO container number, chassis, port/gate fees) is
# drayage, not over-the-road freight (Tumalo TXGU7820247 + CHASSIS RENTAL).
_CONTAINER = re.compile(r"\b[A-Z]{4}\d{7}\b|\bCHASSIS\b|\bGATE FEES?\b|\bPORT SURCHARGE\b|\bPRE[- ]?PULL\b")


def _line_amount(e: Dict[str, Any]) -> float:
    for k in ("total", "amount"):
        try:
            v = float(str(e.get(k)).replace(",", "").replace("$", ""))
            if v:
                return v
        except (TypeError, ValueError):
            pass
    try:
        return float(e.get("quantity") or 0) * float(str(e.get("unit_price")).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


SPLIT_FREIGHT = True


def single_line(coding: Dict[str, Any], doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = coding["dominant"]
    total = round(abs(float(doc["amount_float"])), 2)
    code, ltype = dom["lineObjectNumber"], dom["lineType"]
    src = f"AP codes this vendor {code} ({int(dom['share'] * 100)}% of recent invoices)"
    lines: List[Dict[str, Any]] = []
    if SPLIT_FREIGHT and str(code).upper() in _FREIGHT_CODES:
        items = ((doc.get("extracted_fields") or {}).get("line_items") or [])
        text = " ".join(str(e.get("description") or "") for e in items).upper()
        if str(code).upper() == "FREIGHT" and _CONTAINER.search(text):
            code, ltype, src = "DRAYAGE", "Item", src + "; a port container move: DRAYAGE"
        for e in items:
            for rx, acc in _ACCESSORIALS:
                amt = round(_line_amount(e), 2)
                if rx.search(str(e.get("description") or "")) and 0 < amt < total:
                    lines.append({"lineType": "Item", "lineObjectNumber": acc, "description": str(e.get("description"))[:100],
                                  "quantity": 1.0, "unitCost": amt, "source": f"{acc} line on the invoice"})
                    break
    rest = round(total - sum(l["unitCost"] for l in lines), 2)
    if rest <= 0:
        lines, rest = [], total
    return [{"lineType": ltype, "lineObjectNumber": code,
             "description": f"Invoice {doc.get('invoice_number_clean') or ''}".strip()[:100],
             "quantity": 1.0, "unitCost": rest, "source": src}] + lines




async def is_product_vendor(db, coding) -> bool:
    """AP's main lines for this vendor are mostly product items (bottles,
    caps, cans... - an item category that is not PALLET), not G/L accounts
    (Hwa Hsia 14500 in transit) or service charges (Reiles freight /
    warehouse): such invoices are invoiced against BC receipts."""
    from services.sales_item_xref_service import load_item_categories, is_product
    if not coding or (coding.get("invoices") or 0) < 5 or coding.get("dominant"):
        return False
    await load_item_categories(db)
    mains = coding.get("main_codes") or []
    total = sum(m.get("n") or 0 for m in mains)
    prod = sum(m.get("n") or 0 for m in mains if m.get("lineType") == "Item" and is_product(m.get("code")))
    return bool(total) and prod / total >= 0.6
