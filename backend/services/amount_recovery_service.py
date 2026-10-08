"""Hourly: recover invoice amounts the extractor got wrong, from the PDF's
own text.

Freight bills (XPO, TForce) had the shipment weight read as the amount
("1,055 lbs" -> $1,055); intake now drops such amounts
(amount_weight_suspect). The PDF text layer states the real figure
("TOTAL DUE: US $532.85"); when it states exactly one, that is the amount.
"""
import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TOTAL_DUE = re.compile(r"(?:TOTAL\s+(?:AMOUNT\s+)?DUE|AMOUNT\s+DUE|BALANCE\s+DUE)\s*:?\s*(?:US\s*|USD\s*)?\$?\s*([\d,]+\.\d{2})", re.I)


def _pdf_text(doc: Dict[str, Any]) -> str:
    import pymupdf
    from paths import UPLOAD_DIR
    p = UPLOAD_DIR / doc["id"]
    try:
        if p.exists():
            pdf = pymupdf.open(str(p))
        elif doc.get("file_content_b64"):
            pdf = pymupdf.open(stream=base64.b64decode(doc["file_content_b64"]), filetype="pdf")
        else:
            return ""
        return "\n".join(pg.get_text() for pg in pdf)
    except Exception:
        return ""


def total_due(text: str) -> Optional[float]:
    vals = {round(float(m.replace(",", "")), 2) for m in _TOTAL_DUE.findall(text or "")}
    return vals.pop() if len(vals) == 1 else None


async def reclassify_order_confirmations(db, apply: bool = True, days: int = 30) -> int:
    """A supplier's order confirmation read as an AP invoice (Berry
    '10446843 SR.PDF': no invoice number, 'ORDER CONFIRMATION' on the
    page) sat in Needs staff as 'number missing'. Only when no invoice
    number was found and the file name does not say invoice (Ardagh
    'Invoice no 6012327555' carries both words)."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    n = 0
    async for d in db.hub_documents.find({"created_utc": {"$gte": since}, "mailbox_category": "AP", "document_type": "AP_Invoice",
                                          "invoice_number_clean": {"$in": [None, ""]}, "bc_link": {"$exists": False},
                                          "order_confirmation_checked": {"$exists": False}}):
        upd: Dict[str, Any] = {"order_confirmation_checked": True}
        if not re.search(r"invoice", str(d.get("file_name") or ""), re.I) and re.search(r"ORDER\s+(CONFIRMATION|ACKNOWLEDG)", _pdf_text(d).upper()):
            n += 1
            upd.update({"document_type": "Order_Confirmation", "document_type_previous": d.get("document_type"),
                        "document_type_corrected": {"at": datetime.now(timezone.utc).isoformat(), "reason": "order confirmation, not an invoice"}})
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": upd})
    return n


async def recover(db, apply: bool = True, limit: int = 300) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out = {"checked": 0, "recovered": 0, "examples": [],
           "order_confirmations": await reclassify_order_confirmations(db, apply)}
    async for d in db.hub_documents.find({"amount_weight_suspect": {"$exists": True}, "amount_float": None,
                                          "amount_recovery_tried": {"$exists": False}}).limit(limit):
        out["checked"] += 1
        amt = total_due(_pdf_text(d))
        upd: Dict[str, Any] = {"amount_recovery_tried": now}
        if amt and abs(amt - float(d["amount_weight_suspect"])) > 0.001:
            out["recovered"] += 1
            if len(out["examples"]) < 10:
                out["examples"].append((d.get("vendor_canonical"), d.get("invoice_number_clean"), amt, (d.get("bc_link") or {}).get("bc_amount")))
            upd.update({"amount_float": amt, "amount_raw": f"{amt:.2f}", "amount_source": "pdf_total_due"})
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": upd})
    return out
