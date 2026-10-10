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
import re
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
            # filed_by_staff: staff filed it in Square9 but AP has not entered it
            # in BC yet - drafting it gets it graded against AP's entry (the
            # learning signal), and it is half of each day's invoices.
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "ap_stage": {"$in": ["ready", "awaiting_receipt", "filed_by_staff"]},
             "fraud_risk.flagged": {"$ne": True},
             "document_type": "AP_Invoice", "is_duplicate": {"$ne": True}, "bc_link": {"$exists": False},
             "invoice_number_clean": {"$nin": [None, ""]}, "amount_float": {"$gt": 0},
             "bc_purchase_invoice.environment": {"$ne": ALLOWED_ENVIRONMENT},
             "sandbox_draft_skipped": {"$exists": False}},
            {"_id": 0, "file_content_b64": 0}).sort([("created_utc", -1)]):   # newest first: beat AP's same-day entry
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
                        q, uc = float(l["quantity"]), float(l.get("unitCost") or 0)
                        if q < 0 < uc:
                            # A credit on the receipt (-1 x 37.78 energy
                            # surcharge, accrued dunnage): AP enters 1 x -37.78.
                            q, uc = -q, -uc
                        lines.append({"lineType": _line_type(l.get("lineType")), "lineObjectNumber": l["lineObjectNumber"],
                                      "description": (l.get("description") or "")[:100], "quantity": q,
                                      "unitCost": uc, "source": f"bc_receipt {recs[i]['number']}"})
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



_MULTI_NUMBER = re.compile(r"[A-Za-z0-9-]{4,}\s*(?:,|;|&|\band\b)\s*[A-Za-z0-9-]{4,}")


async def header_problem(db, d: Dict[str, Any], shapes: Dict[str, Any]) -> str:
    """Why this document's header must not be drafted, or "".

    Used for new drafts and to re-check drafts already in the sandbox
    (audit_existing): FASTTRA statement "116854, 116890, 116938" and a
    Westrock "Open Invoices" list were drafted as one invoice under the
    numbers run together, Vidrala "17" and Dayton "125" (= the amount)
    from multi-invoice PDFs - all before these checks existed.
    """
    from services.number_shape_service import fits
    raw = str(d.get("invoice_number_raw") or "")
    num = re.sub(r"[^A-Z0-9]", "", str(d.get("invoice_number_clean") or "").upper())
    if _MULTI_NUMBER.search(raw):
        return f"the document lists several invoice numbers ({raw[:60]}): a statement or several invoices in one file"
    if len(num.lstrip("0")) < 4:
        return f"invoice number {d.get('invoice_number_clean')} is too short to be a real invoice number"
    try:
        amt = float(d.get("amount_float") or 0)
        if amt and num in {str(int(amt)), f"{amt:.2f}".replace(".", "")}:
            return f"invoice number {d.get('invoice_number_clean')} is the invoice amount, not its number"
    except Exception:
        pass
    shape_fit = fits(shapes.get(str(d.get("vendor_canonical") or "").upper()), d.get("invoice_number_clean"))
    if shape_fit is False:
        return f"invoice number {d.get('invoice_number_clean')} does not look like this vendor's invoice numbers in BC"
    # The file is named after a vendor invoice AP already entered (Xolution
    # XO-IN-2026-0033.pdf drafted under the forwarder's freight-bill number).
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{5,}", str(d.get("file_name") or "")):
        t = re.sub(r"[^A-Z0-9]", "", tok.upper()).lstrip("0")
        if len(t) < 6 or t == num.lstrip("0") or not re.search(r"\d{3}", t):
            continue
        hit = await db.bc_reference_cache.find_one(
            {"bc_vendor_no": d.get("vendor_canonical"), "normalized_external_ref": t,
             "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]}, "bc_status": {"$ne": "Canceled"}},
            {"_id": 0, "bc_document_no": 1, "bc_external_document_no": 1})
        if hit:
            return (f"the file name is invoice {hit.get('bc_external_document_no')}, already in Production BC "
                    f"(BC {hit.get('bc_document_no')})")
    # Already entered by AP under another number? Same vendor and amount in
    # Production BC within 60 days of receipt -> do not draft a duplicate.
    try:
        recv = datetime.fromisoformat(str(d.get("created_utc"))[:19])
        lo, hi = (recv - timedelta(days=60)).date().isoformat(), (recv + timedelta(days=60)).date().isoformat()
        amt = abs(float(d["amount_float"]))
        # Only a BC invoice no other Hub document accounts for can be this
        # one under another number: vendors bill repeat amounts (Tumalo
        # flat 785.00, ATS 500.00, Canpack) - 27 false skips 2026-10-07.
        async for b in db.bc_reference_cache.find(
                {"bc_vendor_no": d["vendor_canonical"], "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]},
                 "bc_status": {"$ne": "Canceled"}, "bc_posting_date": {"$gte": lo, "$lte": hi},
                 "bc_amount": {"$gte": amt - 0.02, "$lte": amt + 0.02}},
                {"_id": 0, "bc_document_no": 1, "bc_external_document_no": 1, "bc_posting_date": 1, "bc_order_number": 1}):
            # A number that fits the vendor's shape is a different invoice
            # from an older one for the same amount (Hwa Hsia bills the same
            # container amount every few weeks); only a twin entered around
            # or after receipt can be this invoice under another number.
            if shape_fit and str(b.get("bc_posting_date") or "") < (recv - timedelta(days=14)).date().isoformat():
                continue
            # Both numbers look like this vendor's and differ by more than a
            # typo: two invoices (Tumalo 0314549 vs 313885 on the same 4450
            # lane, Owens 51591194 vs 1588070). Unless BC's number is this
            # invoice's PO: AP enters CM Forwarding (45499-00) and Fast Track
            # (119147) under the PO - those twins are this invoice.
            other = str(b.get("bc_external_document_no") or "")
            po_digits = re.sub(r"-0+$", "", str(d.get("po_number_clean") or "").upper())
            if shape_fit and fits(shapes.get(str(d.get("vendor_canonical") or "").upper()), other) \
                    and other.upper() not in (po_digits, str(b.get("bc_order_number") or "").upper()) \
                    and _edit_distance(num.lstrip("0"), other.upper().lstrip("0")) > 2:
                continue
            # BC's number is another Hub document's own invoice number: that
            # one is in BC, not this one (Anchor 4909838-41 and Owens
            # 51591953/54 all 'matched' the first one AP entered, before
            # reconcile linked it).
            ext = str(b.get("bc_external_document_no") or "").strip().upper()
            if ext and ext != str(d.get("invoice_number_clean") or "").strip().upper() and await db.hub_documents.count_documents(
                    {"vendor_canonical": d["vendor_canonical"], "invoice_number_clean": ext, "id": {"$ne": d["id"]}}, limit=1):
                continue
            if not await db.hub_documents.count_documents({"bc_link.bc_document_no": b["bc_document_no"], "id": {"$ne": d["id"]}}, limit=1):
                return (f"BC already has invoice {b.get('bc_external_document_no')} (BC {b.get('bc_document_no')}) "
                        f"from this vendor for the same amount")
    except Exception:
        pass
    # Same vendor invoice number already in Production BC (any amount):
    # the duplicate lookup in the draft path only checks the sandbox.
    n = num.lstrip("0")
    same_no = await db.bc_reference_cache.find_one(
        {"bc_vendor_no": d["vendor_canonical"], "normalized_external_ref": n,
         "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice", "purchase_credit_memo"]},
         "bc_status": {"$ne": "Canceled"}},
        {"_id": 0, "bc_document_no": 1}) if n else None
    if same_no:
        return f"Production BC already has this vendor invoice number (BC {same_no.get('bc_document_no')}): same vendor invoice number"
    return ""



def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


async def po_in_bc(db, po: str) -> bool:
    """A Gamer purchase order in Production BC (the cache misses fully
    received orders such as Canpack 118340; then ask BC, read-only)."""
    if await db.bc_reference_cache.find_one({"bc_entity_type": "purchase_order", "bc_document_no": po}, {"_id": 1}):
        return True
    import httpx
    import services.bc_catalog_sync_service as bc
    try:
        token = await bc.get_bc_token(environment="Production")
        cid = await bc.get_bc_company_id(environment="Production")
        base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
        async with httpx.AsyncClient(timeout=60) as c:
            for ent, field in (("purchaseOrders", "number"), ("purchaseReceipts", "orderNumber")):
                r = await c.get(f"{base}/{ent}", headers={"Authorization": f"Bearer {token}"},
                                params={"$filter": f"{field} eq '{po}'", "$select": "number", "$top": "1"})
                if r.status_code == 200 and r.json().get("value"):
                    return True
    except Exception:
        return False
    return False


async def po_open_lines(db, po: str) -> List[Dict[str, Any]]:
    """The open (not yet invoiced) lines of a Gamer purchase order in
    Production BC, read-only. Dropship orders (Ball, O-I, Anchor, Amcor) have
    no receipt until the customer's shipment posts, but the invoice arrives
    first - and the PO lines are the invoice: Ball 116378 = 202.4 M x 132.95
    = 26,909.08 + its dunnage line."""
    import httpx
    import services.bc_catalog_sync_service as bc
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{base}/purchaseOrders", headers={"Authorization": f"Bearer {token}"}, params={
            "$filter": f"number eq '{po}'",
            "$expand": "purchaseOrderLines($select=lineType,lineObjectNumber,description,quantity,directUnitCost,invoicedQuantity,unitOfMeasureCode)",
            "$select": "number"})
    if r.status_code != 200:
        return []
    out = []
    for x in r.json().get("value", []):
        for l in x.get("purchaseOrderLines") or []:
            if not l.get("lineObjectNumber"):
                continue
            q = float(l.get("quantity") or 0) - float(l.get("invoicedQuantity") or 0)
            if q <= 0:
                continue
            out.append({"lineType": _line_type(l.get("lineType")), "lineObjectNumber": l["lineObjectNumber"],
                        "description": (l.get("description") or "")[:100], "quantity": round(q, 5),
                        "unitCost": float(l.get("directUnitCost") or 0), "source": f"bc_purchase_order {po}"})
    return out


PROFILE_TO_STAFF = True
WAREHOUSE_SPLIT = True


_WH_CODES = {"WHSESTORAGE", "WHSEHANDLING"}
# A warehouse that also bills freight and Canadian sales tax (CRALER:
# storage 600.00 + Ontario HST 78.00 -> WHSESTORAGE + GST/HST TAX).
# Line replay 2026-10-09: on, 1 more draft and it was wrong (5/6 vs 5/5): off.
WAREHOUSE_SPLIT_TAX_FREIGHT = False
_WH_EXTRA = {"FREIGHT", "GST/HST TAX"}
_TAX_LINE = re.compile(r"\b(?:HST|GST|PST|QST|TPS|TVQ|TVH)\b|sales tax", re.I)


def warehouse_split(d: Dict[str, Any], coding: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """A warehouse's storage & handling bill as AP enters it: one storage
    line and one handling line, quantity 1 at the summed amounts (LSI
    storage 178.50 + handling 399.00), not the per-pallet lines of the PDF.
    Only for vendors AP codes with just WHSESTORAGE / WHSEHANDLING, and only
    when the invoice's own lines add up to its total."""
    if not WAREHOUSE_SPLIT or not coding:
        return None
    used = set(coding.get("codes_used") or [])
    allowed = _WH_CODES | (_WH_EXTRA if WAREHOUSE_SPLIT_TAX_FREIGHT else set())
    if not used or not used <= allowed or not used & _WH_CODES:
        return None
    items = (d.get("extracted_fields") or {}).get("line_items") or []
    from services.vendor_line_coding_service import _line_amount
    buckets: Dict[str, float] = {}
    for e in items:
        amt = round(_line_amount(e), 2)
        if not amt:
            continue
        desc = str(e.get("description") or "")
        if WAREHOUSE_SPLIT_TAX_FREIGHT and _TAX_LINE.search(desc):
            code = "GST/HST TAX"        # CRALER: Ontario HST on its own line
        elif re.search(r"storage|entreposage|rent|recurring", desc, re.I):
            code = "WHSESTORAGE"
        elif WAREHOUSE_SPLIT_TAX_FREIGHT and "FREIGHT" in used and re.search(r"freight|transport|delivery|drayage|line ?haul|fuel", desc, re.I):
            code = "FREIGHT"
        else:
            code = "WHSEHANDLING"
        buckets[code] = round(buckets.get(code, 0) + amt, 2)
    total = round(abs(float(d.get("amount_float") or 0)), 2)
    if not buckets or abs(sum(buckets.values()) - total) > 0.02:
        return None
    if set(buckets) - used:
        # A code AP has never used for this vendor: fold it into the one they use.
        only = sorted(used)[0] if len(used) == 1 else None
        if not only:
            return None
        buckets = {only: total}
    return [{"lineType": "Item", "lineObjectNumber": c, "description": ("Storage" if c == "WHSESTORAGE" else "Handling") + f" - invoice {d.get('invoice_number_clean') or ''}",
             "quantity": 1.0, "unitCost": v, "source": "storage / handling totals, as AP enters this warehouse"} for c, v in sorted(buckets.items())]


FORWARDER_SPLIT = True
# Line replay 2026-10-09: StraitLink 4/6 exact (AP adds a 125 line not on the
# bill; duties sometimes TARIFF) - below the bar the other drafting rules meet: off.
CUSTOMS_BROKER_LINES = False
_CUSTOMS_LINE = re.compile(r"customs|clearance|\bISF\b|\bFDA\b|\bentry\b|\bbond\b|\bduty\b|\bduties\b", re.I)
_DOC_LINE = re.compile(r"documentation|doc(?:ument)? fee", re.I)
_FREIGHT_WORDS = re.compile(r"freight|ocean|\bEXW\b|\bCFR\b|\bFOB\b|\bCIF\b|transport|drayage|trucking|delivery", re.I)


def forwarder_split(d: Dict[str, Any], coding: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """A freight forwarder's bill as AP enters it (Cargo Modules, 7 of 7):
    FREIGHT = the freight line, CUSTOMS = customs clearance + ISF + FDA +
    documentation added together (95 + 25 + 35 + 30 = 185); with no customs
    fee on the bill, documentation rides with the freight. Charge lines on a
    warehouse order (W / WR), Item lines otherwise. Only for vendors AP
    codes with FREIGHT and CUSTOMS, and only when the lines add up."""
    if not FORWARDER_SPLIT or not coding:
        return None
    used = set(coding.get("codes_used") or [])
    from services.vendor_line_coding_service import _line_amount
    items = (d.get("extracted_fields") or {}).get("line_items") or []
    po = str(d.get("po_number_clean") or "").strip().upper()
    ltype = "Charge" if re.match(r"^(?:W|WR|WTR)-?\d", po) else "Item"
    if CUSTOMS_BROKER_LINES and used <= {"CUSTOMS", "TARIFF"} and "CUSTOMS" in used:
        # A customs broker (StraitLink, 10 of 10): one CUSTOMS line per bill
        # line - the 125.00 entry fee and the duties - as AP enters them.
        out = [{"lineType": ltype, "lineObjectNumber": "CUSTOMS", "description": f"customs {po} {str(e.get('description') or '')}".strip()[:100],
                "quantity": 1.0, "unitCost": round(_line_amount(e), 2), "source": "customs broker lines, as AP enters this vendor"}
               for e in items if round(_line_amount(e), 2)]
        total = round(abs(float(d.get("amount_float") or 0)), 2)
        return out if out and abs(sum(l["unitCost"] for l in out) - total) <= 0.02 else None
    if not {"FREIGHT", "CUSTOMS"} <= used:
        return None
    if not any(_FREIGHT_WORDS.search(str(e.get("description") or "")) for e in items):
        return None
    has_customs = any(_CUSTOMS_LINE.search(str(e.get("description") or "")) for e in items)
    buckets: Dict[str, float] = {}
    for e in items:
        amt = round(_line_amount(e), 2)
        if not amt:
            continue
        desc = str(e.get("description") or "")
        code = "CUSTOMS" if has_customs and (_CUSTOMS_LINE.search(desc) or _DOC_LINE.search(desc)) else "FREIGHT"
        buckets[code] = round(buckets.get(code, 0) + amt, 2)
    total = round(abs(float(d.get("amount_float") or 0)), 2)
    if "FREIGHT" not in buckets or abs(sum(buckets.values()) - total) > 0.02:
        return None
    label = {"FREIGHT": "Ocean", "CUSTOMS": "Customs Fee"}
    return [{"lineType": ltype, "lineObjectNumber": c, "description": f"{po} {label[c]}".strip()[:100], "quantity": 1.0,
             "unitCost": buckets[c], "source": "freight / customs totals, as AP enters this forwarder"}
            for c in ("FREIGHT", "CUSTOMS") if c in buckets]


PREPAY_BEFORE_RECEIPT = True
_PREPAY_ACCOUNTS = {"14500"}


async def prepay_lines(db, d: Dict[str, Any], coding: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """A vendor AP prepays before the goods arrive (Hwa Hsia: 9 of 15
    invoices are 'Ppay Inv. HH-150728A' on G/L 14500 for the full amount,
    the PO's item at quantity 0). Only while nothing on the PO is received
    and the PO's total IS the invoice: a bill for several containers is
    entered by AP as one invoice per container (HH-150730A, -1, -2)."""
    if not PREPAY_BEFORE_RECEIPT or not coding:
        return None
    mains = coding.get("main_codes") or []
    total_n = sum(m.get("n") or 0 for m in mains)
    pre = [m for m in mains if m.get("lineType") == "Account" and str(m.get("code")) in _PREPAY_ACCOUNTS]
    if not pre or not total_n or pre[0]["n"] < 3 or pre[0]["n"] / total_n < 0.5:
        return None
    po = str(d.get("po_number_clean") or "").strip().upper()
    amt = round(abs(float(d.get("amount_float") or 0)), 2)
    if not po or not amt:
        return None
    import httpx
    import services.bc_catalog_sync_service as bc
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{base}/purchaseOrders", headers={"Authorization": f"Bearer {token}"}, params={
            "$filter": f"number eq '{po}'",
            "$expand": "purchaseOrderLines($select=lineObjectNumber,quantity,directUnitCost,receivedQuantity,invoicedQuantity)",
            "$select": "number,vendorNumber"})
    vals = r.json().get("value", []) if r.status_code == 200 else []
    if len(vals) != 1 or str(vals[0].get("vendorNumber") or "").upper() != str(d.get("vendor_canonical") or "").upper():
        return None
    ls = [l for l in vals[0].get("purchaseOrderLines") or [] if l.get("lineObjectNumber") and float(l.get("quantity") or 0)]
    if not ls or any(float(l.get("receivedQuantity") or 0) or float(l.get("invoicedQuantity") or 0) for l in ls):
        return None
    if abs(sum(float(l["quantity"]) * float(l.get("directUnitCost") or 0) for l in ls) - amt) > 0.02:
        return None
    return [{"lineType": "Account", "lineObjectNumber": pre[0]["code"],
             "description": f"Ppay Inv. {d.get('invoice_number_clean') or ''}".strip()[:100], "quantity": 1.0, "unitCost": amt,
             "source": f"prepayment before receipt on {pre[0]['code']}, as AP enters this vendor"}]


async def plan_lines(db, d: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    """The lines a draft of this invoice gets (see vendor_line_coding_service).

    Returns {"lines", "source"} | {"wait": reason} | {"problem": reason}.
    """
    from routers.gpi_integration import _build_pi_lines_with_mapping
    from services.vendor_line_coding_service import coding_for, single_line, main_code_known
    if rec.get("lines"):
        return {"lines": rec["lines"], "source": "bc_receipt"}
    coding = await coding_for(db, d.get("vendor_canonical"))
    if coding and coding.get("dominant"):
        return {"lines": single_line(coding, d), "source": "vendor_coding"}
    try:
        pp = await prepay_lines(db, d, coding)
    except Exception:
        pp = None
    if pp:
        return {"lines": pp, "source": "prepay"}
    po = str(d.get("po_number_clean") or "").strip().upper()
    from services.vendor_line_coding_service import is_product_vendor
    if po and await is_product_vendor(db, coding):
        # No receipt yet: the PO's open lines, when they ARE the invoice
        # (to the cent - every draft's total is verified in BC).
        try:
            pl = await po_open_lines(db, po)
        except Exception:
            pl = []
        if pl and abs(sum(l["quantity"] * l["unitCost"] for l in pl) - abs(float(d.get("amount_float") or 0))) <= 0.02:
            return {"lines": pl, "source": "bc_purchase_order"}
        if await po_in_bc(db, po):
            return {"wait": f"PO {po} has no BC receipt that adds up to this invoice yet; AP invoices this vendor against receipts"}
    if await is_product_vendor(db, coding):
        # A product vendor: the right lines are the PO's received items.
        return {"problem": (f"PO {po} is not a purchase order or receipt in BC" if po else "the invoice shows no PO")
                           + "; AP invoices this vendor against PO receipts, so the Hub cannot draft its lines"}
    fl = forwarder_split(d, coding)
    if fl:
        return {"lines": fl, "source": "forwarder_split"}
    try:
        lines = await _build_pi_lines_with_mapping(d, db, vendor_no=d["vendor_canonical"])
    except Exception as e:
        return {"problem": f"line build failed: {e!r}"[:200]}
    problem = lines_problem(lines)
    if problem:
        return {"problem": problem}
    if main_code_known(coding, lines) is False:
        m = max([l for l in lines if l.get("lineObjectNumber")], key=lambda l: abs(float(l.get("quantity") or 0) * float(l.get("unitCost") or 0)), default={})
        return {"problem": f"the Hub would code this {m.get('lineObjectNumber')}, which AP has not used for this vendor in BC"}
    wl = warehouse_split(d, coding)
    if wl:
        return {"lines": wl, "source": "warehouse_split"}
    if PROFILE_TO_STAFF:
        # Replay vs AP's BC entries (2026-10-08): these lines were right 4 of
        # 16 times (warehouse storage/handling splits, customs + tariff).
        return {"problem": "AP codes this vendor's invoices in varying ways (no usual coding the Hub can follow)"}
    return {"lines": lines, "source": "vendor_profile"}


# Lines built by a rule measured against AP's entries (not the old vendor
# profile builder): the audit leaves them alone.
PLANNED_SOURCES = {"bc_receipt", "bc_purchase_order", "vendor_coding", "forwarder_split", "warehouse_split", "prepay"}


async def audit_existing(db, apply: bool = True) -> Dict[str, Any]:
    """Re-check the Hub's own sandbox drafts against today's header checks.

    A draft AP has not touched (read-back state "draft", no edits) that
    would not be drafted today is removed from the sandbox and the invoice
    goes to staff with the reason. Drafts AP edited are left alone.
    """
    from services.number_shape_service import vendor_shapes
    if refusal():
        return {"refused": refusal()}
    from routers.gpi_integration import _delete_orphan_pi_header
    shapes = await vendor_shapes(db)
    now = datetime.now(timezone.utc).isoformat()
    out = {"checked": 0, "removed": [], "kept_edited": 0}
    async for d in db.hub_documents.find({"bc_purchase_invoice.environment": ALLOWED_ENVIRONMENT}, {"_id": 0}):
        out["checked"] += 1
        rb = d.get("bc_draft_readback") or {}
        if rb.get("edits"):
            out["kept_edited"] += 1
            continue
        problem = await header_problem(db, d, shapes)
        requeue = False
        if not problem and rb.get("hub_side_changes"):
            # The invoice changed in the Hub after it was drafted (and nobody
            # has touched the draft): replace it with one from today's data.
            problem = "the invoice changed in the Hub after drafting (" + "; ".join(rb["hub_side_changes"])[:150] + "); re-drafting"
            requeue = True
        if not problem:
            from services.vendor_line_coding_service import coding_for, main_code_known, is_product_vendor
            lines = d.get("draft_lines_planned") or (rb.get("lines") or [])
            coding = await coding_for(db, d.get("vendor_canonical"))
            # vendor_coding lines are AP's own coding plus the accessorial /
            # container rules the line replay measured (Tumalo container move
            # -> DRAYAGE): removing them re-drafted the same lines hourly.
            if d.get("draft_lines_source") not in PLANNED_SOURCES and lines \
                    and main_code_known(coding, lines) is False:
                problem = "drafted with lines AP does not use for this vendor; re-drafting from AP's coding or the BC receipt"
                requeue = True
            elif d.get("draft_lines_source") not in PLANNED_SOURCES - {"vendor_coding"} and d.get("po_number_clean") \
                    and await is_product_vendor(db, coding) \
                    and str((max([l for l in lines if l.get("lineObjectNumber")], key=lambda l: abs(float(l.get("quantity") or 0) * float(l.get("unitCost") or 0)), default={}) or {}).get("lineType") or "Item") == "Item":
                # A product vendor drafted from guessed lines (before receipts
                # were used: Berry CD24410... where AP posted M-CAP-38MMTE).
                problem = "a product invoice drafted without its BC receipt; re-drafting from the receipt once it posts"
                requeue = True
            elif (coding or {}).get("dominant") and d.get("draft_lines_source") not in PLANNED_SOURCES \
                    and len([l for l in lines if l.get("lineObjectNumber")]) > 1:
                # AP codes this vendor as one line (R+L: one FREIGHT line); the
                # older builder split it (2 x 6,415.19, -1 x 11,868.09, ...).
                problem = "drafted as several lines; AP codes this vendor as one line - re-drafting that way"
                requeue = True
        if not problem:
            continue
        if requeue and (d.get("bc_purchase_invoice_removed") or {}).get("reason") == problem:
            # Removed for this already and re-drafted the same way: staff.
            requeue = False
            problem += " (the re-draft came out the same; needs AP's lines)"
        pi = d["bc_purchase_invoice"]
        out["removed"].append({"bc_record_no": pi.get("bc_record_no"), "vendor": d.get("vendor_canonical"),
                               "number": d.get("invoice_number_clean"), "reason": problem})
        if not apply:
            continue
        deleted = await _delete_orphan_pi_header(pi.get("bc_system_id"))
        await db.hub_documents.update_one({"id": d["id"]}, {
            "$set": {"bc_purchase_invoice_removed": {**pi, "removed_at": now, "reason": problem, "delete_result": deleted,
                                                     # kept for grading against what AP entered in Production
                                                     "lines": (rb.get("lines") or d.get("draft_lines_planned") or [])},
                     **({} if requeue else {"sandbox_draft_skipped": {"reason": problem, "at": now}}),
                     **({"ap_stage": "ready"} if requeue else {})},
            "$unset": {"bc_purchase_invoice": "", "bc_purchase_invoice_no": "", "bc_draft_readback": "",
                       "draft_lines_planned": "", "draft_lines_override": ""}})
        await db.ap_workflow_events.insert_one({"document_id": d["id"], "action": "sandbox_draft_removed", "by": "hub", "at": now,
                                                "environment": ALLOWED_ENVIRONMENT, "bc_record_no": pi.get("bc_record_no"),
                                                "detail": {"reason": problem, "delete_result": deleted}})
    return out


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

    for d in await candidates(db, limit * 10):
        if len(results) >= limit:
            break
        problem = await header_problem(db, d, shapes)
        if problem:
            await skip(d, problem)
            continue
        # Waiting for a receipt: re-check BC every 3 hours, not every hour.
        wr = d.get("draft_waiting_receipt") or {}
        if wr and str(wr.get("checked_at") or "") > (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat():
            continue
        try:
            rec_probe = await receipt_lines_for(db, d)
        except Exception:
            rec_probe = {}
        plan = await plan_lines(db, d, rec_probe)
        if plan.get("wait") and wr.get("since") and str(wr["since"]) < (datetime.now(timezone.utc) - timedelta(days=10)).isoformat():
            await skip(d, f"waited 10 days for a BC receipt that adds up to this invoice: {plan['wait']}")
            continue
        if plan.get("wait"):
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"draft_waiting_receipt": {
                "reason": plan["wait"], "po": d.get("po_number_clean"), "since": wr.get("since") or datetime.now(timezone.utc).isoformat(),
                "checked_at": datetime.now(timezone.utc).isoformat()}}})
            continue
        problem = plan.get("problem", "")
        if problem:
            skipped.append({"document_id": d["id"], "file_name": d.get("file_name"), "reason": problem})
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
                "reason": problem, "at": datetime.now(timezone.utc).isoformat()}}})
            continue
        # Keep the exact lines this draft uses, to compare with what AP later
        # enters in Production BC (draft quality, learned per vendor).
        try:
            used_lines = plan.get("lines") or []
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"draft_lines_planned": [
                {k: l.get(k) for k in ("lineType", "lineObjectNumber", "description", "quantity", "unitCost")}
                for l in (used_lines or []) if isinstance(l, dict)]}})
        except Exception:
            pass
        legacy = d.get("bc_purchase_invoice") and (d["bc_purchase_invoice"].get("environment") != ALLOWED_ENVIRONMENT)
        if plan.get("source") == "bc_receipt":
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "draft_lines_override": plan["lines"], "draft_receipt_numbers": rec_probe["receipts"],
                "draft_lines_source": "bc_receipt"}, "$unset": {"draft_waiting_receipt": ""}})
        elif plan.get("source") == "bc_purchase_order":
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "draft_lines_override": plan["lines"], "draft_lines_source": "bc_purchase_order"},
                "$unset": {"draft_waiting_receipt": ""}})
        elif plan.get("lines") and plan.get("source") not in (None, "vendor_profile"):
            # Every planned source the drafter must use as planned (vendor
            # coding, forwarder / warehouse splits, prepayment): before
            # 2026-10-10 only vendor_coding was passed on, and the forwarder
            # plan fell back to the profile builder (FREIGHT-WH item charges
            # PRE does not have - 0/5 lines, an orphan header every hour).
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "draft_lines_override": plan["lines"], "draft_lines_source": plan["source"]}})
        else:
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"draft_lines_source": "vendor_profile"},
                                                               "$unset": {"draft_lines_override": ""}})
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
        msg = str(r.get("message") or r.get("error") or "")
        if "partial_post" in msg:
            # BC took the header but refused the lines: remove the empty
            # header (our own sandbox draft) and park the invoice with BC's
            # reason, instead of a new orphan header every hour.
            import re as _re
            sid = r.get("bc_system_id") or (_re.search(r"system_id=([0-9a-f-]{36})", msg) or [None, None])[1]
            deleted = None
            if sid:
                from routers.gpi_integration import _delete_orphan_pi_header
                try:
                    deleted = await _delete_orphan_pi_header(sid)
                except Exception as e:
                    deleted = repr(e)[:120]
            why = (_re.search(r"message[^A-Za-z]{1,12}([A-Za-z][^\\\"]{3,160})", msg) or [None, msg[-200:]])[1]
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sandbox_draft_skipped": {
                "reason": f"BC refused the draft lines ({why}); line build failed", "header_removed": str(deleted)[:80],
                "at": datetime.now(timezone.utc).isoformat()}}})
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




_LINE_PROBLEM = re.compile(r"do not add up|negative balancing|line build failed|would code this|has not used for this vendor|varying ways", re.I)
_SKIP_NUMBER = re.compile(r"invoice number (\S+) (?:is too short|does not look like)", re.I)
_SKIP_PO = re.compile(r"PO (\S+) is not a purchase order or receipt in BC", re.I)
STALE_SKIP_HOURS = 72


async def _skip_is_stale(db, d, reason: str) -> Optional[str]:
    """Why a skip no longer holds, or None. Skips record the state at the
    time (Dayton "125" before the number was corrected to 838404656, a PO
    purchasing had not entered yet). Only BC purchase orders count: Gamer
    sales orders and shipments reuse the same number range."""
    m = _SKIP_NUMBER.search(reason)
    if m and m.group(1).upper() != str(d.get("invoice_number_clean") or "").upper():
        return "invoice number corrected"
    m = _SKIP_PO.search(reason)
    if m and await db.bc_reference_cache.find_one({"bc_entity_type": "purchase_order", "bc_document_no": m.group(1)}, {"_id": 1}):
        return "PO now in BC"
    at = str((d.get("sandbox_draft_skipped") or {}).get("at") or "")
    if at and at < (datetime.now(timezone.utc) - timedelta(hours=STALE_SKIP_HOURS)).isoformat():
        return f"re-checked after {STALE_SKIP_HOURS}h"
    return None


async def retry_line_skips(db) -> Dict[str, Any]:
    """Skipped invoices are retried once the skip no longer holds: a line
    problem whose vendor AP now codes as a single line (XPO: FREIGHT on 15/15,
    skipped before that rule existed), a number since corrected, a PO since
    entered in BC, or any skip older than STALE_SKIP_HOURS (re-skipped with a
    fresh reason if it still holds)."""
    from services.vendor_line_coding_service import coding_for
    n = 0
    why = {}
    async for d in db.hub_documents.find({"sandbox_draft_skipped.reason": {"$exists": True}, "bc_link": {"$exists": False},
                                          "bc_purchase_invoice.environment": {"$ne": ALLOWED_ENVIRONMENT}},
                                         {"_id": 1, "vendor_canonical": 1, "sandbox_draft_skipped": 1, "invoice_number_clean": 1}):
        reason = str((d.get("sandbox_draft_skipped") or {}).get("reason") or "")
        stale = await _skip_is_stale(db, d, reason)
        if not stale and _LINE_PROBLEM.search(reason) and (await coding_for(db, d.get("vendor_canonical")) or {}).get("dominant"):
            stale = "vendor now has a usual coding"
        if not stale:
            continue
        await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"sandbox_draft_skipped_previous": {**d["sandbox_draft_skipped"], "retried_because": stale}},
                                                               "$unset": {"sandbox_draft_skipped": ""}})
        why[stale] = why.get(stale, 0) + 1
        n += 1
    return {"retried": n, "why": why}
