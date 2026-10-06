"""Draft (never post) BC purchase invoices in the PRE sandbox, for AP review.

Decided with the business 2026-10-06: the Hub drafts but does not post;
drafts go to the PRE cutover sandbox first; AP folders stay part of the
workflow. This service is the only automatic way the Hub drafts:

* only documents whose ap_stage is "ready" (vendor, number, amount and
  folder known with confidence, or decided by staff), AP invoices only
  for now, with a BC vendor number, an invoice number and an amount,
  not already entered by AP in Production BC (bc_link) and not already
  drafted in the sandbox;
* the write environment must be exactly ALLOWED_ENVIRONMENT (PRE); any
  other target - and anything Production - refuses before any BC call;
* uses the existing draft path (gpi_integration.create_purchase_invoice_
  from_document: duplicate lookup in BC by vendor + vendor invoice number,
  lines from the vendor profile, refuses when lines do not add up to the
  invoice total, removes an orphan header) with the Hub's BC-learned
  vendor number. Nothing here posts: no posting call exists in the Hub.
* preview() shows exactly what would be drafted without calling BC.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ALLOWED_ENVIRONMENT = os.environ.get("BC_DRAFT_ALLOWED_ENVIRONMENT", "PRE_GAMERDOCS_CUTOVER_20260831")


def write_target() -> str:
    from services.gpi_integration_service import BC_WRITE_ENVIRONMENT
    return BC_WRITE_ENVIRONMENT


def refusal() -> str:
    if os.environ.get("BC_WRITE_ENABLED", "false").strip().lower() != "true":
        return "BC writes are disabled (BC_WRITE_ENABLED is not true)"
    target = write_target()
    if target != ALLOWED_ENVIRONMENT:
        return f"Write environment is '{target}', drafting is only allowed in '{ALLOWED_ENVIRONMENT}'"
    if "prod" in target.lower():
        return "Drafting never targets Production"
    return ""


async def candidates(db, limit: int = 25, days: int = 30) -> List[Dict[str, Any]]:
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no"))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out, seen = [], set()
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "ap_stage": "ready",
             "document_type": "AP_Invoice", "is_duplicate": {"$ne": True}, "bc_link": {"$exists": False},
             "invoice_number_clean": {"$nin": [None, ""]}, "amount_float": {"$gt": 0},
             "bc_purchase_invoice.environment": {"$ne": ALLOWED_ENVIRONMENT}},
            {"_id": 0, "file_content_b64": 0}).sort([("created_utc", 1)]):
        if d.get("vendor_canonical") not in bc_vendors:
            continue
        key = (d["vendor_canonical"], str(d["invoice_number_clean"]).upper())
        if key in seen:  # two Hub copies of one invoice: draft once
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= limit:
            break
    return out


def lines_problem(planned) -> str:
    """A draft AP can stand behind: no invented negative balancing lines on
    an invoice (the line builder forces the total with a negative line when
    extracted quantities or prices are wrong, e.g. XPO qty 1000 and -12,925.85)."""
    if not isinstance(planned, list) or not planned:
        return "no lines could be built"
    for l in planned:
        try:
            if float(l.get("unitCost") or 0) * float(l.get("quantity") or 1) < 0:
                return "a negative balancing line was needed; the extracted lines do not add up"
        except (TypeError, ValueError):
            return "a line has no usable amount"
    return ""


async def preview(db, limit: int = 10) -> Dict[str, Any]:
    from routers.gpi_integration import _build_pi_lines_with_mapping
    items = []
    for d in await candidates(db, limit):
        try:
            lines = await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"])
        except Exception as e:
            lines = {"error": repr(e)[:200]}
        planned = lines if isinstance(lines, list) else (lines.get("lines") if isinstance(lines, dict) else None)
        total = None
        if isinstance(planned, list):
            try:
                total = round(sum(float(l.get("quantity") or 1) * float(l.get("unitCost") or l.get("directUnitCost") or 0)
                                  for l in planned), 2)
            except Exception:
                total = None
        ef = d.get("extracted_fields") or {}
        items.append({
            "document_id": d["id"], "file_name": d.get("file_name"), "vendor_no": d.get("vendor_canonical"),
            "vendor_invoice_no": d.get("invoice_number_clean"), "invoice_date": ef.get("invoice_date"),
            "amount": d.get("amount_float"), "po": d.get("po_number_clean"), "folder": d.get("suggested_folder"),
            "legacy_draft_exists": bool(d.get("bc_purchase_invoice")),
            "planned_lines": planned if isinstance(planned, list) else lines,
            "planned_total": total,
            "lines_match_amount": total is not None and abs(total - float(d.get("amount_float") or 0)) < 0.02,
            "lines_problem": lines_problem(planned) or None,
        })
    return {"target": write_target(), "allowed": ALLOWED_ENVIRONMENT, "refusal": refusal() or None, "items": items}


async def draft(db, limit: int = 5) -> Dict[str, Any]:
    reason = refusal()
    if reason:
        return {"drafted": 0, "refused": reason}
    from routers.gpi_integration import create_purchase_invoice_from_document
    results: List[Dict[str, Any]] = []
    from routers.gpi_integration import _build_pi_lines_with_mapping
    skipped = []
    for d in await candidates(db, limit * 3):
        if len(results) >= limit:
            break
        try:
            problem = lines_problem(await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"]))
        except Exception as e:
            problem = f"line build failed: {e!r}"[:200]
        if problem:
            skipped.append({"document_id": d["id"], "file_name": d.get("file_name"), "reason": problem})
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
                "reason": problem, "at": datetime.now(timezone.utc).isoformat()}}})
            continue
        legacy = d.get("bc_purchase_invoice") and (d["bc_purchase_invoice"].get("environment") != ALLOWED_ENVIRONMENT)
        try:
            r = await create_purchase_invoice_from_document(
                d["id"], vendor_no_override=d["vendor_canonical"], force=bool(legacy))
            if not isinstance(r, dict):
                r = {"result": str(r)[:200]}
        except Exception as e:
            r = {"success": False, "error": getattr(e, "detail", None) or repr(e)[:300]}
        results.append({"document_id": d["id"], "file_name": d.get("file_name"), "vendor_no": d.get("vendor_canonical"),
                         "vendor_invoice_no": d.get("invoice_number_clean"), "amount": d.get("amount_float"),
                         "success": bool(r.get("success")) and not r.get("already_exists"),
                         "bc_record_no": r.get("bc_record_no"), "detail": {k: r.get(k) for k in
                                                                            ("status", "message", "error", "lines_added", "lines_total", "already_exists")}})
        await db.ap_workflow_events.insert_one({"document_id": d["id"], "action": "sandbox_draft", "by": "hub",
                                                "at": datetime.now(timezone.utc).isoformat(), "environment": write_target(),
                                                "success": results[-1]["success"], "bc_record_no": r.get("bc_record_no"),
                                                "detail": results[-1]["detail"]})
    return {"target": write_target(), "drafted": sum(1 for x in results if x["success"]), "results": results,
            "skipped": skipped}

