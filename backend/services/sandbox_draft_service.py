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
    # Paused 2026-10-07: read-back found drafts whose BC total differs from
    # the invoice (R+L 593.74 -> 3,154.68). Resume once fixed.
    if os.environ.get("SANDBOX_DRAFTING_PAUSED", "true").strip().lower() == "true":
        return "Sandbox drafting is paused (SANDBOX_DRAFTING_PAUSED)"
    if os.environ.get("BC_WRITE_ENABLED", "false").strip().lower() != "true":
        return "BC writes are disabled (BC_WRITE_ENABLED is not true)"
    target = write_target()
    if target != ALLOWED_ENVIRONMENT:
        return f"Write environment is '{target}', drafting is only allowed in '{ALLOWED_ENVIRONMENT}'"
    if "prod" in target.lower():
        return "Drafting never targets Production"
    return ""


async def verify_draft_total(system_id: str, expected: float) -> Dict[str, Any]:
    """Read the draft just created back from BC and compare its total with
    the invoice (read-only GET)."""
    import httpx
    import services.bc_catalog_sync_service as bc
    env = ALLOWED_ENVIRONMENT
    token = await bc.get_bc_token(environment=env)
    async with httpx.AsyncClient(timeout=60) as c:
        comps = (await c.get(f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies",
                             headers={"Authorization": f"Bearer {token}"})).json().get("value", [])
        cid = next((x["id"] for x in comps if "gamer" in str(x.get("name", "")).lower()), comps[0]["id"] if comps else None)
        r = await c.get(f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies({cid})/purchaseInvoices({system_id})",
                        headers={"Authorization": f"Bearer {token}"}, params={"$select": "number,totalAmountIncludingTax,totalAmountExcludingTax"})
    if r.status_code != 200:
        return {"ok": None, "error": r.status_code}
    v = r.json()
    total = float(v.get("totalAmountIncludingTax") or 0)
    excl = float(v.get("totalAmountExcludingTax") or 0)
    ok = abs(total - abs(expected)) < 0.02 or abs(excl - abs(expected)) < 0.02
    return {"ok": ok, "bc_total": total, "expected": expected}


async def candidates(db, limit: int = 25, days: int = 30) -> List[Dict[str, Any]]:
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no"))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    # Already drafted from another Hub copy of the same invoice (BC's own
    # duplicate check refused R+L I848946906 the second time).
    seen = set()
    async for x in db.hub_documents.find({"bc_purchase_invoice.environment": ALLOWED_ENVIRONMENT},
                                         {"_id": 0, "vendor_canonical": 1, "invoice_number_clean": 1}):
        seen.add((x.get("vendor_canonical"), str(x.get("invoice_number_clean") or "").upper()))
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "ap_stage": "ready",
             "document_type": "AP_Invoice", "is_duplicate": {"$ne": True}, "bc_link": {"$exists": False},
             "invoice_number_clean": {"$nin": [None, ""]}, "amount_float": {"$gt": 0},
             "bc_purchase_invoice.environment": {"$ne": ALLOWED_ENVIRONMENT},
             "sandbox_draft_skipped": {"$exists": False}},
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


def _line_type(raw: str) -> str:
    t = str(raw or "").replace("_x0020_", " ").replace("_x002F_", "/").replace("_x0028_", "(").replace("_x0029_", ")").strip()
    if t.lower().startswith("g/l") or t.lower() == "account":
        return "Account"
    if t.lower().startswith("charge"):
        return "Charge"
    return t or "Item"


async def receipt_lines_for(db, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Draft lines from the BC purchase receipt this invoice is for.

    AP invoices PO-based purchases against what was received; the receipt's
    item lines are exactly the invoice's (60/60 orders checked) and one
    receipt's lines add up to the invoice total (80/80, 2026-10-06), where
    the vendor-profile line builder matched BC's item only 51% of the time
    (it coded Ball / O-I / Canpack product as pallets). Read-only BC GET.
    """
    import itertools
    import httpx
    import services.bc_catalog_sync_service as bc
    order = str(doc.get("po_number_clean") or "").strip().upper()
    amount = abs(float(doc.get("amount_float") or 0))
    if not order or not amount:
        return {}
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{base}/purchaseReceipts", headers={"Authorization": f"Bearer {token}"}, params={
            "$filter": f"orderNumber eq '{order}'",
            "$expand": "purchaseReceiptLines($select=lineType,lineObjectNumber,description,quantity,unitCost,unitOfMeasureCode)",
            "$select": "number,orderNumber,postingDate"})
    if r.status_code != 200:
        return {}
    used = set(await db.hub_documents.distinct("draft_receipt_numbers", {"id": {"$ne": doc.get("id")}}))
    recs = [x for x in r.json().get("value", []) if x.get("number") not in used]

    def item_lines(rec):
        return [l for l in rec.get("purchaseReceiptLines", []) if l.get("lineObjectNumber") and float(l.get("quantity") or 0)]

    tots = [round(sum(float(l["quantity"]) * float(l.get("unitCost") or 0) for l in item_lines(x)), 2) for x in recs]
    for k in range(1, min(3, len(recs)) + 1):
        for combo in itertools.combinations(range(len(recs)), k):
            if abs(sum(tots[i] for i in combo) - amount) <= max(1.0, 0.002 * amount):
                lines = []
                for i in combo:
                    for l in item_lines(recs[i]):
                        lines.append({"lineType": _line_type(l.get("lineType")), "lineObjectNumber": l["lineObjectNumber"],
                                      "description": (l.get("description") or "")[:100], "quantity": float(l["quantity"]),
                                      "unitCost": float(l.get("unitCost") or 0), "source": f"bc_receipt {recs[i]['number']}"})
                return {"lines": lines, "receipts": [recs[i]["number"] for i in combo], "order": order}
    return {}


def lines_problem(planned) -> str:
    """A draft AP can stand behind: no invented negative balancing lines on
    an invoice (the line builder forces the total with a negative line when
    extracted quantities or prices are wrong, e.g. XPO qty 1000 and -12,925.85)."""
    if not isinstance(planned, list) or not planned:
        return "no lines could be built"
    for l in planned:
        try:
            amount = float(l.get("unitCost") or 0) * float(l.get("quantity") or 1)
        except (TypeError, ValueError):
            return "a line has no usable amount"
        # A real discount line (R+L, XPO freight bills) is fine; a negative
        # line the line builder invented to force the total is not.
        if amount < 0 and (l.get("reconciled") or l.get("reconcile_info")):
            return "a negative balancing line was needed; the extracted lines do not add up"
    return ""


async def preview(db, limit: int = 10) -> Dict[str, Any]:
    from routers.gpi_integration import _build_pi_lines_with_mapping
    items = []
    for d in await candidates(db, limit):
        try:
            rec = await receipt_lines_for(db, d)
        except Exception:
            rec = {}
        try:
            lines = rec.get("lines") or await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"])
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
            "lines_source": f"BC receipt {', '.join(rec['receipts'])}" if rec.get("lines") else "vendor profile",
        })
    return {"target": write_target(), "allowed": ALLOWED_ENVIRONMENT, "refusal": refusal() or None, "items": items}


async def draft(db, limit: int = 5) -> Dict[str, Any]:
    reason = refusal()
    if reason:
        return {"drafted": 0, "refused": reason}
    from routers.gpi_integration import create_purchase_invoice_from_document
    results: List[Dict[str, Any]] = []
    from routers.gpi_integration import _build_pi_lines_with_mapping
    from services.number_shape_service import vendor_shapes, fits
    shapes = await vendor_shapes(db)
    skipped = []

    async def skip(d, reason):
        skipped.append({"document_id": d["id"], "file_name": d.get("file_name"), "reason": reason})
        await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
            "reason": reason, "at": datetime.now(timezone.utc).isoformat()}}})

    for d in await candidates(db, limit * 3):
        if len(results) >= limit:
            break
        # The number must look like this vendor's invoice numbers in BC.
        if fits(shapes.get(str(d["vendor_canonical"]).upper()), d.get("invoice_number_clean")) is False:
            await skip(d, f"invoice number {d.get('invoice_number_clean')} does not look like this vendor's invoice numbers in BC")
            continue
        # Already entered by AP under another number? Same vendor and amount in
        # Production BC within 60 days of receipt -> do not draft a duplicate.
        try:
            recv = datetime.fromisoformat(str(d.get("created_utc"))[:19])
            lo, hi = (recv - timedelta(days=60)).date().isoformat(), (recv + timedelta(days=60)).date().isoformat()
            amt = abs(float(d["amount_float"]))
            twin = await db.bc_reference_cache.find_one(
                {"bc_vendor_no": d["vendor_canonical"], "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]},
                 "bc_status": {"$ne": "Canceled"}, "bc_posting_date": {"$gte": lo, "$lte": hi},
                 "bc_amount": {"$gte": amt - 0.02, "$lte": amt + 0.02}},
                {"_id": 0, "bc_document_no": 1, "bc_external_document_no": 1})
        except Exception:
            twin = None
        if twin:
            await skip(d, f"BC already has invoice {twin.get('bc_external_document_no')} (BC {twin.get('bc_document_no')}) "
                          f"from this vendor for the same amount")
            continue
        # Same vendor invoice number already in Production BC (any amount):
        # the duplicate lookup in the draft path only checks the sandbox.
        import re as _re
        num = _re.sub(r"[^A-Z0-9]", "", str(d.get("invoice_number_clean") or "").upper()).lstrip("0")
        same_no = await db.bc_reference_cache.find_one(
            {"bc_vendor_no": d["vendor_canonical"], "normalized_external_ref": num,
             "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice", "purchase_credit_memo"]},
             "bc_status": {"$ne": "Canceled"}},
            {"_id": 0, "bc_document_no": 1}) if num else None
        if same_no:
            await skip(d, f"Production BC already has this vendor invoice number (BC {same_no.get('bc_document_no')}): same vendor invoice number")
            continue
        try:
            rec_probe = await receipt_lines_for(db, d)
        except Exception:
            rec_probe = {}
        try:
            problem = "" if rec_probe.get("lines") else lines_problem(await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"]))
        except Exception as e:
            problem = f"line build failed: {e!r}"[:200]
        if problem:
            skipped.append({"document_id": d["id"], "file_name": d.get("file_name"), "reason": problem})
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
                "reason": problem, "at": datetime.now(timezone.utc).isoformat()}}})
            continue
        # Keep the exact lines this draft uses, to compare with what AP later
        # enters in Production BC (draft quality, learned per vendor).
        try:
            used_lines = (rec_probe.get("lines") if rec_probe.get("lines")
                          else await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"]))
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"draft_lines_planned": [
                {k: l.get(k) for k in ("lineType", "lineObjectNumber", "description", "quantity", "unitCost")}
                for l in (used_lines or []) if isinstance(l, dict)]}})
        except Exception:
            pass
        legacy = d.get("bc_purchase_invoice") and (d["bc_purchase_invoice"].get("environment") != ALLOWED_ENVIRONMENT)
        try:
            rec = await receipt_lines_for(db, d)
        except Exception:
            rec = {}
        if rec.get("lines"):
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "draft_lines_override": rec["lines"], "draft_receipt_numbers": rec["receipts"],
                "draft_lines_source": "bc_receipt"}})
        try:
            r = await create_purchase_invoice_from_document(
                d["id"], vendor_no_override=d["vendor_canonical"], force=bool(legacy))
            if not isinstance(r, dict):
                r = {"result": str(r)[:200]}
        except Exception as e:
            r = {"success": False, "error": getattr(e, "detail", None) or repr(e)[:300]}
        if (r.get("error") == "line_total_mismatch" or (isinstance(r.get("error"), dict) and r["error"].get("error") == "line_total_mismatch")
                or "line_total_mismatch" in str(r.get("error") or "")):
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
                "reason": "the extracted lines do not add up to the invoice total",
                "detail": str(r.get("error"))[:300], "at": datetime.now(timezone.utc).isoformat()}}})
        if r.get("success") and not r.get("already_exists") and r.get("bc_system_id"):
            # Verify in BC that the draft's total is the invoice total; a draft
            # that came out different is removed (our own sandbox draft) and
            # the invoice goes to staff.
            try:
                chk = await verify_draft_total(r["bc_system_id"], float(d["amount_float"]))
            except Exception as e:
                chk = {"ok": None, "error": repr(e)[:120]}
            if chk.get("ok") is False:
                from routers.gpi_integration import _delete_orphan_pi_header
                deleted = await _delete_orphan_pi_header(r["bc_system_id"])
                await db.hub_documents.update_one({"id": d["id"]}, {
                    "$set": {"sandbox_draft_skipped": {"reason": f"draft total in BC {chk['bc_total']} differed from the invoice {chk['expected']}; draft removed ({deleted})",
                                                       "at": datetime.now(timezone.utc).isoformat()},
                             "bc_purchase_invoice_last_failure": d.get("bc_purchase_invoice")},
                    "$unset": {"bc_purchase_invoice": "", "bc_purchase_invoice_no": ""}})
                r = {"success": False, "error": f"total mismatch after draft ({chk['bc_total']} vs {chk['expected']}); removed"}
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

