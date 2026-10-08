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


async def recover(db, apply: bool = True, limit: int = 300) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out = {"checked": 0, "recovered": 0, "examples": []}
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
