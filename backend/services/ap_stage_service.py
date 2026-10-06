"""One clear stage per AP document, and one reason when staff must act.

The older status fields (status, workflow_status, workflow_state,
derived_workflow_state, validation_state, needs_review, review_queue,
routing_status, automation_decision, queue_visible) overlap and contradict
each other (2026-10-06: 186 documents "Completed" yet needs_review; 934
derived "needs_review" while workflow_state "ready"). They are left in
place but no longer answer "does a person need to touch this?". These do:

ap_stage (exactly one):
  no_action      duplicate, CFDI companion, split continuation, or not an AP
                 document (tax-exemption request, statement, notice ...)
  needs_staff    a person must decide; staff_reason says what
  ready          vendor, invoice number, amount and folder known with
                 confidence; waiting for AP to enter it in BC
  in_bc          AP entered it in BC (BC is now the truth)
  in_bc_check    entered, but BC's amount or invoice number differs
  paid           BC shows it paid
  container      the original PDF that was split into pieces (never work)

staff_reason (only for needs_staff), most important first:
  suspected_fraud, vendor_unknown, number_or_amount_missing,
  po_not_in_bc, routing_uncertain (with suggested_folder: the decision path
  is below 90% agreement with staff filings, or has too little evidence).

Routing confidence is measured, not assumed: reason_accuracy holds, per
routing decision path, how often the Hub's folder matched the staff
filing (seeded from 45 days of filings, refreshed by the daily replay).
A path graduates to automatic at >= 90% over >= 10 filings.
"""
import csv
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

RELIABLE_PCT = 90.0
RELIABLE_MIN_N = 10
WINDOW_DAYS = 45

NO_ACTION_TYPES = {"Statement", "Remittance", "Unknown_Document", "Inventory_Report", "Graphics_Artwork",
                   "Order_Confirmation", "Quality_Document", "Packing_Slip", "Sales_Quote"}
INVOICE_TYPES = {"AP_Invoice", "AP_INVOICE", "Credit_Memo"}
CAUGHT = {"exact_match", "strong_evidence_match", "likely_match", "possible_match"}


def reason_key(why: str) -> str:
    """A routing reason with its specifics (orders, vendors, folders) removed,
    so decisions of the same kind are measured together."""
    w = re.sub(r"\d+", "#", why or "")
    w = re.sub(r"→ .*", "→ X", w)
    w = re.sub(r"\(was: .*", "(was: ...)", w)
    w = re.sub(r"\(vendor=.*", "(vendor=...)", w)
    w = re.sub(r"order [A-Z]*#[A-Z]?", "order #", w)
    w = re.sub(r"PO \S+", "PO #", w)
    return w[:80]


def _root(p: str) -> str:
    r = (p or "").strip("/")
    if r.lower().startswith("temp folder/"):
        r = r[12:]
    r = r.split("/")[0].lower()
    return "s&h" if r.startswith("s&h") else r


async def measure_reason_accuracy(db, csv_path: str, source: str) -> Dict[str, Any]:
    """Route each staff-filed document (BC link removed, as at intake) and
    store one outcome per document in routing_outcomes (reason key, agreed
    or not); re-measuring replaces it, so overlapping windows never count a
    filing twice. Reliability uses outcomes from the last WINDOW_DAYS."""
    from services.folder_routing_service import route_with_feedback
    seen = set()
    try:
        rows = list(csv.DictReader(open(csv_path)))
    except FileNotFoundError:
        return {"error": f"missing {csv_path}"}
    now = datetime.now(timezone.utc).isoformat()
    n = agree = 0
    for r in rows:
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
            path, why, _ = await route_with_feedback(d, is_international=bool(d.get("is_international")))
        except Exception:
            continue
        hit = _root(path) == _root(r.get("square9_parent_path"))
        n += 1
        agree += hit
        await db.routing_outcomes.update_one({"hub_doc_id": r["hub_doc_id"]}, {"$set": {
            "hub_doc_id": r["hub_doc_id"], "reason_key": reason_key(why), "agreed": hit,
            "hub_folder": path, "staff_folder": r.get("square9_parent_path"),
            "filed_at": d.get("created_utc"), "measured_at": now, "source": source}}, upsert=True)
    return {"filings": n, "agreed": agree}


async def load_reliability(db) -> Dict[str, Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    out = {}
    async for g in db.routing_outcomes.aggregate([
            {"$match": {"filed_at": {"$gte": since}}},
            {"$group": {"_id": "$reason_key", "n": {"$sum": 1}, "ok": {"$sum": {"$cond": ["$agreed", 1, 0]}}}}]):
        n, ok = g["n"], g["ok"]
        pct = round(100 * ok / n, 1) if n else 0.0
        out[g["_id"]] = {"n": n, "pct": pct, "reliable": n >= RELIABLE_MIN_N and pct >= RELIABLE_PCT}
    return out

def stage_of(d: Dict[str, Any], bc_vendors: set, route: Optional[Tuple[str, str]],
             reliability: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The stage of one document. route = (folder, reason) at intake view, or
    None when routing is not needed for the decision."""
    if d.get("status") == "batch_parent":
        return {"ap_stage": "container"}
    if d.get("is_duplicate"):
        return {"ap_stage": "no_action", "no_action_reason": d.get("duplicate_reason") or "duplicate"}
    if d.get("non_ap_kind") or d.get("document_type") in NO_ACTION_TYPES:
        return {"ap_stage": "no_action", "no_action_reason": d.get("non_ap_kind") or "not_ap:" + str(d.get("document_type"))}
    bl = d.get("bc_link") if isinstance(d.get("bc_link"), dict) else None
    if bl and bl.get("bc_document_no"):
        if str(bl.get("bc_status") or "").lower() == "paid" or bl.get("bc_entity") == "posted_purchase_invoice":
            return {"ap_stage": "paid"}
        if d.get("bc_amount_mismatch") or d.get("bc_number_typo_suspect"):
            return {"ap_stage": "in_bc_check",
                    "check_reason": "number_differs" if d.get("bc_number_typo_suspect") else "amount_differs"}
        return {"ap_stage": "in_bc"}
    if (d.get("fraud_risk") or {}).get("flagged"):
        return {"ap_stage": "needs_staff", "staff_reason": "suspected_fraud"}
    if d.get("vendor_canonical") not in bc_vendors:
        return {"ap_stage": "needs_staff", "staff_reason": "vendor_unknown"}
    if d.get("document_type") in INVOICE_TYPES and (not d.get("invoice_number_clean") or d.get("amount_float") in (None, 0, 0.0)):
        return {"ap_stage": "needs_staff", "staff_reason": "number_or_amount_missing"}
    if route:
        folder, why = route
        if not (folder or "").strip("/") or "not found as" in (why or ""):
            return {"ap_stage": "needs_staff", "staff_reason": "po_not_in_bc", "suggested_folder": folder, "routing_reason": why}
        rel = reliability.get(reason_key(why)) or {"n": 0, "pct": None, "reliable": False}
        if not rel["reliable"]:
            return {"ap_stage": "needs_staff", "staff_reason": "routing_uncertain", "suggested_folder": folder,
                    "routing_reason": why, "routing_path_accuracy": rel}
        return {"ap_stage": "ready", "suggested_folder": folder, "routing_reason": why, "routing_path_accuracy": rel}
    return {"ap_stage": "ready"}


async def refresh_stages(db, days: int = 30, apply: bool = True) -> Dict[str, Any]:
    from services.folder_routing_service import route_with_feedback
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no"))
    reliability = await load_reliability(db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    counts, reasons, uncertain = Counter(), Counter(), Counter()
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP"}, {"file_content_b64": 0}):
        pre = stage_of(d, bc_vendors, None, reliability)
        res = pre
        if pre["ap_stage"] == "ready":
            x = {k: v for k, v in d.items() if k != "_id"}
            x.pop("bc_link", None)
            try:
                folder, why, _ = await route_with_feedback(x, is_international=bool(d.get("is_international")))
                res = stage_of(d, bc_vendors, (folder, why), reliability)
            except Exception as e:
                res = {"ap_stage": "needs_staff", "staff_reason": "routing_error", "routing_reason": repr(e)[:120]}
        counts[res["ap_stage"]] += 1
        if res.get("staff_reason"):
            reasons[res["staff_reason"]] += 1
            if res["staff_reason"] == "routing_uncertain":
                uncertain[reason_key(res.get("routing_reason"))] += 1
        if apply:
            unset = {k: "" for k in ("staff_reason", "suggested_folder", "routing_reason", "routing_path_accuracy",
                                     "no_action_reason", "check_reason") if k not in res}
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {**res, "ap_stage_updated_at": now},
                                                                  **({"$unset": unset} if unset else {})})
    out = {"stages": dict(counts), "staff_reasons": dict(reasons), "uncertain_paths": dict(uncertain.most_common(15))}
    logger.info("[APStage] %s", out)
    return out

