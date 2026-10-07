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


def single_line(coding: Dict[str, Any], doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = coding["dominant"]
    return [{"lineType": dom["lineType"], "lineObjectNumber": dom["lineObjectNumber"],
             "description": f"Invoice {doc.get('invoice_number_clean') or ''}".strip()[:100],
             "quantity": 1.0, "unitCost": round(abs(float(doc["amount_float"])), 2),
             "source": f"AP codes this vendor {dom['lineObjectNumber']} ({int(dom['share'] * 100)}% of recent invoices)"}]

