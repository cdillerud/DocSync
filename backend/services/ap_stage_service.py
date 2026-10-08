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
  drafted        the Hub drafted it in the BC sandbox (PRE); AP reviews the draft
  on_hold        a person put it on hold (ap_hold: reason, until)
  awaiting_approval  waiting for a named approver (ap_approval), or an S&H
                 invoice not yet approved (as Square9 "waiting for approval")
  filed_by_staff staff already filed it in Square9 (their filing is the
                 decision; it feeds routing_outcomes)
  file_only      supporting paperwork (shipping documents, BOLs, receipts,
                 inspection forms): filed to the Hub's best folder, no AP
                 decision to make; staff can still correct it

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

SUPPORTING_TYPES = {"Shipping_Document", "Warehouse_Receipt", "Freight_Document", "Inspection_Form",
                    "Warehouse_Document", "Packing_Slip"}


def stage_of(d: Dict[str, Any], bc_vendors: set, route: Optional[Tuple[str, str]],
             reliability: Dict[str, Dict[str, Any]], staff_filed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The stage of one document. route = (folder, reason) at intake view, or
    None when routing is not needed for the decision."""
    if d.get("status") == "batch_parent":
        return {"ap_stage": "container"}
    if d.get("is_duplicate"):
        return {"ap_stage": "no_action", "no_action_reason": d.get("duplicate_reason") or "duplicate"}
    if d.get("non_transactional") or d.get("excluded_from_processing"):
        return {"ap_stage": "no_action", "no_action_reason": "excluded_by_staff:" + str(d.get("non_transactional_reason") or d.get("non_transactional_disposition") or "")}
    if d.get("document_type") == "AR_Invoice" and re.search(r"statement", f"{d.get('file_name') or ''} {d.get('email_subject') or ''}", re.I):
        return {"ap_stage": "no_action", "no_action_reason": "statement"}
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
    # Drafted by the Hub in the BC sandbox (sandbox_draft_service): waiting
    # for AP to review the draft.
    bpi = d.get("bc_purchase_invoice") if isinstance(d.get("bc_purchase_invoice"), dict) else None
    if bpi and bpi.get("environment") and bpi.get("status") == "Draft":
        return {"ap_stage": "drafted", "bc_draft_no": bpi.get("bc_record_no"), "bc_draft_environment": bpi.get("environment")}
    # Holds and approvals (ap_workflow_service), before AP enters the invoice.
    if isinstance(d.get("ap_hold"), dict):
        return {"ap_stage": "on_hold"}
    appr = d.get("ap_approval") if isinstance(d.get("ap_approval"), dict) else None
    if appr and appr.get("status") == "pending":
        return {"ap_stage": "awaiting_approval"}
    if appr and appr.get("status") == "rejected":
        return {"ap_stage": "needs_staff", "staff_reason": "approval_rejected"}
    approved = bool(appr and appr.get("status") == "approved")
    sd = d.get("staff_decision") if isinstance(d.get("staff_decision"), dict) else None
    if sd and sd.get("folder"):
        return {"ap_stage": "ready", "suggested_folder": sd["folder"], "staff_decided": True}
    if staff_filed:
        return {"ap_stage": "filed_by_staff", "suggested_folder": staff_filed.get("staff_folder")}
    if (d.get("fraud_risk") or {}).get("flagged"):
        return {"ap_stage": "needs_staff", "staff_reason": "suspected_fraud"}
    # A piece of a split PDF with no number or amount of its own is a
    # continuation page (the invoice total is on another piece).
    if d.get("batch_parent_id") and (not d.get("invoice_number_clean") or d.get("amount_float") in (None, 0, 0.0)):
        return {"ap_stage": "no_action", "no_action_reason": "split_piece_without_invoice_data"}
    if d.get("document_type") in SUPPORTING_TYPES:
        if route and (route[0] or "").strip("/"):
            return {"ap_stage": "file_only", "suggested_folder": route[0], "routing_reason": route[1]}
        return {"ap_stage": "file_only"}
    if d.get("vendor_canonical") not in bc_vendors:
        return {"ap_stage": "needs_staff", "staff_reason": "vendor_unknown"}
    if d.get("document_type") in INVOICE_TYPES and (not d.get("invoice_number_clean") or d.get("amount_float") in (None, 0, 0.0)):
        return {"ap_stage": "needs_staff", "staff_reason": "number_or_amount_missing"}
    if route:
        folder, why = route
        if not (folder or "").strip("/") or "not found as" in (why or ""):
            return {"ap_stage": "needs_staff", "staff_reason": "po_not_in_bc", "suggested_folder": folder, "routing_reason": why}
        if _root(folder) == "s&h" and not approved:
            return {"ap_stage": "awaiting_approval", "suggested_folder": folder, "routing_reason": why}
        # Non-trade invoices (no Gamer order; Square9 "Misc Invoices - need
        # approval") wait for an approver rather than a folder decision.
        if "need approval" in (folder or "").lower() and not approved:
            return {"ap_stage": "awaiting_approval", "suggested_folder": folder, "routing_reason": why,
                    "approval_kind": "non_trade"}
        rel = reliability.get(reason_key(why)) or {"n": 0, "pct": None, "reliable": False}
        # A folder staff created and named for this invoice's own PO
        # ("Dropship International/120199 120200 120201 120208 120209" for an
        # SGC invoice on PO 120199) is their filing decision already made.
        po = str(d.get("po_number_clean") or "").strip().upper()
        sub = (folder or "").strip("/").split("/")[-1].upper() if "/" in (folder or "").strip("/") else ""
        if po and len(po) >= 5 and po in re.split(r"[\s,;&+]+", sub):
            rel = {**rel, "reliable": True, "via": "existing folder named for this PO"}
        if not rel["reliable"]:
            return {"ap_stage": "needs_staff", "staff_reason": "routing_uncertain", "suggested_folder": folder,
                    "routing_reason": why, "routing_path_accuracy": rel}
        if d.get("draft_waiting_receipt") and not d.get("sandbox_draft_skipped"):
            # A product invoice that arrived before its goods were received in
            # BC: drafted from the receipt once it posts (re-checked every 3h).
            return {"ap_stage": "awaiting_receipt", "suggested_folder": folder, "routing_reason": why,
                    "routing_path_accuracy": rel}
        if d.get("sandbox_draft_skipped"):
            # The Hub could not draft it: the extracted lines do not add up.
            return {"ap_stage": "needs_staff", "staff_reason": "draft_lines_problem", "suggested_folder": folder,
                    "routing_reason": why, "routing_path_accuracy": rel}
        return {"ap_stage": "ready", "suggested_folder": folder, "routing_reason": why, "routing_path_accuracy": rel}
    return {"ap_stage": "ready"}


async def refresh_stages(db, days: int = 30, apply: bool = True) -> Dict[str, Any]:
    from services.folder_routing_service import route_with_feedback
    # Blocked BC vendors are not vendors to pay: their documents go to staff.
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no", {"blocked": {"$ne": True}}))
    reliability = await load_reliability(db)
    staff_filed = {}
    async for o in db.routing_outcomes.find({"source": {"$ne": "staff_decision"}}, {"_id": 0, "hub_doc_id": 1, "staff_folder": 1}):
        staff_filed[o["hub_doc_id"]] = o
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    counts, reasons, uncertain = Counter(), Counter(), Counter()
    # Recent documents, plus older ones still in an active stage (a stage is
    # never left stale: Fort Dearborn's 9/7 statement sat in approvals).
    async for d in db.hub_documents.find(
            {"mailbox_category": "AP", "$or": [{"created_utc": {"$gte": since}},
                                               {"ap_stage": {"$in": ["needs_staff", "awaiting_approval", "on_hold", "ready",
                                                                     "drafted", "awaiting_receipt", "in_bc_check"]}}]},
            {"file_content_b64": 0}):
        sf = staff_filed.get(d.get("id"))
        pre = stage_of(d, bc_vendors, None, reliability, sf)
        res = pre
        if pre["ap_stage"] == "drafted":
            # Drafted invoices keep their AP folder (folders are part of
            # AP's workflow; the draft is only the BC side).
            x = {k: v for k, v in d.items() if k != "_id"}
            x.pop("bc_link", None)
            try:
                folder, why, _ = await route_with_feedback(x, is_international=bool(d.get("is_international")))
                res = {**pre, "suggested_folder": folder, "routing_reason": why}
            except Exception:
                pass
        if pre["ap_stage"] in ("ready", "file_only") and not pre.get("staff_decided"):
            x = {k: v for k, v in d.items() if k != "_id"}
            x.pop("bc_link", None)
            try:
                folder, why, _ = await route_with_feedback(x, is_international=bool(d.get("is_international")))
                res = stage_of(d, bc_vendors, (folder, why), reliability, sf)
            except Exception as e:
                res = {"ap_stage": "needs_staff", "staff_reason": "routing_error", "routing_reason": repr(e)[:120]}
        if res["ap_stage"] == "awaiting_approval" and not (d.get("ap_approval") or {}).get("approver"):
            from services.ap_workflow_service import suggest_approver
            res["suggested_approver"] = await suggest_approver(db, d)
        counts[res["ap_stage"]] += 1
        if res.get("staff_reason"):
            reasons[res["staff_reason"]] += 1
            if res["staff_reason"] == "routing_uncertain":
                uncertain[reason_key(res.get("routing_reason"))] += 1
        if apply:
            unset = {k: "" for k in ("staff_reason", "suggested_folder", "routing_reason", "routing_path_accuracy",
                                     "no_action_reason", "check_reason", "staff_decided", "suggested_approver", "approval_kind",
                                     "bc_draft_no", "bc_draft_environment") if k not in res}
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {**res, "ap_stage_updated_at": now},
                                                                  **({"$unset": unset} if unset else {})})
    out = {"stages": dict(counts), "staff_reasons": dict(reasons), "uncertain_paths": dict(uncertain.most_common(15))}
    logger.info("[APStage] %s", out)
    return out

