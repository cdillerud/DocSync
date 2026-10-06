"""Daily replay of the Hub's current intake logic against ground truth.

Once a day (from the hourly learning cycle) the Hub re-runs what it would
decide today for documents whose answer is now known, so the learning has
a trend line rather than one-off measurements:

* routing: staff Square9 filings from the last 72 hours (parity CSV),
  routed with the BC link removed (what the Hub knows at intake); top
  folder agreement, S&H waiting/approved counted as one (a stage, not a
  routing decision).
* vendor: invoices AP entered in BC in the last 14 days (exact
  number+amount link); intake vendor resolution (sender map, then
  aliases) scored against the BC vendor number.

Stored in learning_metrics (one row per day), shown on the readiness page.
"""
import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

PARITY_CSV = "/app/prod_reports/parity_hourly.csv"
CAUGHT = {"exact_match", "strong_evidence_match", "likely_match", "possible_match"}


def _root(p: str) -> str:
    r = (p or "").strip("/")
    if r.lower().startswith("temp folder/"):
        r = r[12:]
    r = r.split("/")[0].lower()
    return "s&h" if r.startswith("s&h") else r


async def _routing_replay(db) -> Dict[str, Any]:
    from services.folder_routing_service import route_with_feedback
    if not os.path.exists(PARITY_CSV):
        return {"n": 0}
    seen, n, agree = set(), 0, 0
    for r in csv.DictReader(open(PARITY_CSV)):
        ok = r.get("match_bucket") in CAUGHT or (
            r.get("match_bucket") == "recently_deleted_match" and float(r.get("match_score") or 0) >= 1
            and r.get("square9_parent_path"))
        if not ok or not r.get("hub_doc_id") or r["hub_doc_id"] in seen:
            continue
        seen.add(r["hub_doc_id"])
        d = await db.hub_documents.find_one({"id": r["hub_doc_id"]}, {"_id": 0, "file_content_b64": 0})
        if not d:
            continue
        d.pop("bc_link", None)
        d.pop("bc_credit_of", None)
        try:
            path, _, _ = await route_with_feedback(d, is_international=bool(d.get("is_international")))
        except Exception:
            continue
        n += 1
        agree += _root(path) == _root(r.get("square9_parent_path"))
    return {"n": n, "agree": agree, "pct": round(100 * agree / n, 1) if n else None}


async def _vendor_replay(db) -> Dict[str, Any]:
    import services.vendor_matching as vm
    from services.vendor_name_helpers import normalize_vendor_name
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    n = right = 0
    async for d in db.hub_documents.find(
            {"bc_link.match": "number+amount", "created_utc": {"$gte": since}},
            {"_id": 0, "email_sender": 1, "vendor_raw": 1, "extracted_fields.vendor": 1,
             "normalized_fields.vendor_normalized": 1, "bc_link.bc_vendor_no": 1}):
        raw = d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor") or ""
        res: Dict[str, Any] = {}
        try:
            if d.get("email_sender"):
                res = await vm.lookup_vendor_by_sender(d["email_sender"], extracted_vendor=raw, document_id=None)
            if not res.get("vendor_canonical"):
                res = await vm.lookup_vendor_alias((d.get("normalized_fields") or {}).get("vendor_normalized")
                                                   or normalize_vendor_name(raw))
        except Exception:
            res = {}
        n += 1
        right += res.get("vendor_canonical") == d["bc_link"]["bc_vendor_no"]
    return {"n": n, "right": right, "pct": round(100 * right / n, 1) if n else None}


def _n(x) -> str:
    import re
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


async def _draft_replay(db, days: int = 30) -> Dict[str, Any]:
    """Would today's Hub logic have drafted exactly what AP entered in BC?
    For every BC purchase invoice / credit memo posted in the last `days`:
    received (a Hub document is linked to it), and the draft fields from the
    Hub's own reading, before any correction learned from BC: vendor (intake
    resolution replayed), invoice number (raw, after learned per-vendor
    format rules), amount, invoice-vs-credit, and PO where BC has one."""
    import services.vendor_matching as vm
    from services.vendor_name_helpers import normalize_vendor_name
    from services.invoice_number_rules_service import apply_rule
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rules: Dict[str, list] = {}
    async for r in db.vendor_invoice_number_rules.find({}, {"_id": 0, "vendor": 1, "rule": 1}):
        rules.setdefault(str(r.get("vendor") or "").upper(), []).append(r.get("rule"))
    bc = {}
    async for b in db.bc_reference_cache.find(
            {"bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice", "purchase_credit_memo"]},
             "bc_posting_date": {"$gte": since}, "bc_status": {"$ne": "Canceled"}},
            {"_id": 0, "bc_entity_type": 1, "bc_document_no": 1, "bc_vendor_no": 1, "bc_external_document_no": 1,
             "bc_amount": 1, "bc_order_number": 1}):
        bc[(b["bc_entity_type"] == "purchase_credit_memo", b["bc_document_no"])] = b
    out = {"bc_documents": len(bc), "received": 0, "vendor_ok": 0, "number_ok": 0, "amount_ok": 0, "type_ok": 0,
           "draft_exact": 0, "po_checked": 0, "po_ok": 0}
    seen = set()
    async for d in db.hub_documents.find(
            {"bc_link.bc_document_no": {"$exists": True}, "is_duplicate": {"$ne": True}},
            {"_id": 0, "bc_link": 1, "email_sender": 1, "vendor_raw": 1, "extracted_fields.vendor": 1,
             "normalized_fields.vendor_normalized": 1, "invoice_number_clean": 1, "invoice_number_extracted_previous": 1,
             "amount_float": 1, "amount_from_bc": 1, "document_type": 1, "document_type_previous": 1,
             "po_number_clean": 1, "po_number_previous": 1, "po_from_text": 1}):
        bl = d["bc_link"]
        key = (bl.get("bc_entity") == "purchase_credit_memo", bl.get("bc_document_no"))
        b = bc.get(key)
        if not b or key in seen:
            continue
        seen.add(key)
        out["received"] += 1
        raw = d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor") or ""
        res: Dict[str, Any] = {}
        try:
            if d.get("email_sender"):
                res = await vm.lookup_vendor_by_sender(d["email_sender"], extracted_vendor=raw, document_id=None)
            if not res.get("vendor_canonical"):
                res = await vm.lookup_vendor_alias((d.get("normalized_fields") or {}).get("vendor_normalized")
                                                   or normalize_vendor_name(raw))
        except Exception:
            res = {}
        v_ok = res.get("vendor_canonical") == b.get("bc_vendor_no")
        num = d.get("invoice_number_extracted_previous") or d.get("invoice_number_clean")
        cands = {_n(num)} | {_n(apply_rule(r, num)) for r in rules.get(str(b.get("bc_vendor_no") or "").upper(), []) if apply_rule(r, num)}
        n_ok = bool(num) and _n(b.get("bc_external_document_no")) in cands
        a_ok = (not d.get("amount_from_bc") and d.get("amount_float") is not None and b.get("bc_amount") is not None
                and abs(abs(float(d["amount_float"])) - abs(float(bl.get("bc_amount") or b["bc_amount"]))) < 0.02)
        hub_type = d.get("document_type_previous") or d.get("document_type")
        t_ok = (hub_type == "Credit_Memo") == key[0]
        out["vendor_ok"] += v_ok; out["number_ok"] += n_ok; out["amount_ok"] += a_ok; out["type_ok"] += t_ok
        if v_ok and n_ok and a_ok and t_ok:
            out["draft_exact"] += 1
            if b.get("bc_order_number"):
                out["po_checked"] += 1
                hub_po = (d.get("po_from_text") or {}).get("value") or d.get("po_number_previous") or d.get("po_number_clean")
                out["po_ok"] += _n(hub_po) == _n(b["bc_order_number"])
    t = out["bc_documents"] or 1
    out["received_pct"] = round(100 * out["received"] / t, 1)
    out["draft_exact_pct"] = round(100 * out["draft_exact"] / t, 1)
    out["draft_exact_of_received_pct"] = round(100 * out["draft_exact"] / max(out["received"], 1), 1)
    return out


async def record_daily(db, force: bool = False) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    if not force and await db.learning_metrics.find_one({"date": today}, {"_id": 1}):
        return {"skipped": "already measured today"}
    row = {"date": today, "measured_at": datetime.now(timezone.utc).isoformat(),
           "routing": await _routing_replay(db), "vendor": await _vendor_replay(db),
           "draft": await _draft_replay(db)}
    await db.learning_metrics.update_one({"date": today}, {"$set": row}, upsert=True)
    logger.info("[LearningMetrics] %s", row)
    return {k: v for k, v in row.items() if k != "measured_at"}
