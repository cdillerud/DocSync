"""The AI decides the folder where the learned folder model is unsure.

Routing is the rules' folder, then the learned subfolder where the model
trained on staff's filings is confident (folder_learning_service). Where
that model is unsure (top choice under UNSURE), the AI decides instead:
it sees the document, what Business Central says about its order (whose
goods were received on it), the model's top choices with probabilities,
the rules' proposal, and past documents like it with where staff filed
each (document_memory: the vendor's latest filings and documents that read
alike). Added on top of the rules and the model, not in place of them.

Replay on filings after the model's training period (2026-10-25, the
120 latest unsure ones of 1,133 held out): current routing 70 right, the
AI with the vendor's latest filings as examples 79, the AI with each
past document's order shown (received in BC or not, international or not)
and told staff file by the order, not the vendor's habit, 84; plus "a
folder named for a vendor (Ball, dunnage vendors...) goes by the vendor",
86 vs 84 on the same documents.

On only while it earns it: evaluate() replays the latest unsure filings
each day (a model trained on the filings before them, so neither side has
seen the answer) and keeps the AI on only while it is right more often
than current routing on them. One AI call per document: the decision is
kept on the document (ai_routing) and reused by every later routing call.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ai_routing")

AI_ROUTING = True
UNSURE = 0.6            # learned model's top-choice probability under which the AI decides
EVAL_HOURS = 20
EVAL_MAX = 120          # unsure filings replayed per evaluation (one AI call each)
EVAL_CUT = 0.65         # model trained on the earliest 65% of filings, replayed on the rest
MIN_N = 30
POOL_ROWS = 360         # replayed AI answers kept for calibration (about three evaluations)
MIN_GAIN = 0.03         # share of the replayed documents the AI must get right beyond current routing (at least 2)
SAME_VENDOR = 8
SIMILAR = 5

SYSTEM = ("You route Gamer Packaging's accounts-payable documents to the SharePoint folder staff would file them in. "
          "You see the document, what the Hub's order lookup in Business Central says about its order, the folders a model "
          "trained on staff's past filings thinks most likely (with probabilities), the folder the hand-written rules propose, "
          "and past documents like this one with the folder staff filed each in. Decide where staff would file it. "
          "Staff file by the order behind a document (warehouse or dropship, international or not, the order's own folder), "
          "not by what the vendor's last few documents were: compare each past document's order to this one's and follow "
          "the past documents whose order is like this one's. "
          "The exception is a folder named for a vendor or vendor group (Ball, Canpack, dunnage vendors, Evergreen orders and "
          "the like): there the vendor decides, as the vendor's past filings in it show. "
          "Staff also keep a folder per order (e.g. \"warehouse international/w118658\"): the order folder the rules propose, "
          "or one a past document was filed in, is a valid answer too. "
          "Answer JSON only: {\"folder\": \"<a listed folder, the rules' folder, or a past document's folder, exactly as written>\", "
          "\"confidence\": 0-1, \"why\": \"<short>\"}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_base(po: str) -> str:
    """The order a lettered release belongs to (assembly WA2318F -> WA2318), or ''."""
    m = re.match(r"^([A-Z]*[0-9]{3,})[A-Z]{1,2}$", str(po or "").strip().upper())
    return m.group(1) if m else ""


async def _receipts(db, po: str, proj: Dict[str, Any], limit: int = 5) -> Tuple[List[Dict[str, Any]], str]:
    """BC receipts of the order, else of its other releases (WA2318F, not
    received yet: WA2318B, components from MONARCH; staff file an assembly
    order's bills by the site its components go to, ANCH 89/89 GT B&B,
    MONARCH 18/19 Kent)."""
    rs = [r async for r in db.bc_purchase_receipts.find({"orderNumber": po}, proj).limit(limit)]
    base = "" if rs else _release_base(po)
    if base:
        rs = [r async for r in db.bc_purchase_receipts.find({"orderNumber": {"$regex": f"^{base}[A-Z]{{0,2}}$"}}, proj).limit(limit)]
    return rs, base


async def order_facts(db, po: str) -> str:
    if not po:
        return "no order number on the document"
    out = []
    rs, base = await _receipts(db, po, {"_id": 0, "orderNumber": 1, "vendorNumber": 1, "postingDate": 1, "purchaseReceiptLines": 1})
    for r in rs:
        items = [str(l.get("description") or "")[:50] for l in (r.get("purchaseReceiptLines") or []) if l.get("lineObjectNumber")][:3]
        rel = f"its release {r.get('orderNumber')} " if base else ""
        out.append(f"{rel}received from {r.get('vendorNumber')} on {r.get('postingDate')}: {items}")
    so = await db.bc_sales_orders.find_one({"number": po}, {"_id": 0, "customerName": 1, "customerNumber": 1, "shipToName": 1})
    if so:
        out.append(f"sales order for {so.get('customerName') or so.get('customerNumber')} ship to {so.get('shipToName')}")
    return "; ".join(out) or f"order {po}: nothing received in BC yet"


def _label_of(folder: str) -> str:
    from services.folder_learning_service import label
    fo = folder[12:] if folder.lower().startswith("temp folder/") else folder
    parts = [p for p in fo.split("/") if p]
    return label({"top": parts[0] if parts else "", "subpath": "/".join(parts[1:])})


def _folder_of(folder: str) -> str:
    """Top folder and first subfolder as staff spelled them."""
    fo = folder[12:] if folder.lower().startswith("temp folder/") else folder
    return "/".join([p.strip() for p in fo.split("/") if p.strip()][:2])


async def _order_kind(db, po: Any) -> str:
    po = str(po or "").strip().upper()
    if not po:
        return "no order number"
    rs, base = await _receipts(db, po, {"_id": 0, "vendorNumber": 1}, limit=3)
    vendors = sorted({str(r.get("vendorNumber")) for r in rs})
    so = await db.bc_sales_orders.count_documents({"number": po}, limit=1)
    rec = (f"releases of {base} received in BC from {', '.join(vendors)}" if base else
           f"received in BC from {', '.join(vendors)}") if rs else "no BC receipt"
    return f"order {po}: " + rec + ("; also a sales order number" if so else "")


async def _note(db, h: Dict[str, Any], why: str) -> str:
    """What the AI compares: the past document's type and its order."""
    if h.get("source") != "hub":
        return why
    x = await db.hub_documents.find_one({"id": h["item_id"]}, {"_id": 0, "po_number_clean": 1, "document_type": 1,
                                                                "is_international": 1})
    if not x:
        return why
    return (f"{why}; {x.get('document_type')}; {await _order_kind(db, x.get('po_number_clean'))}; "
            f"international={x.get('is_international')}")


_NUM: Dict[str, Any] = {}
NUM_SECONDS = 3600


async def _shared(db, d: Dict[str, Any], before: str, seen: set, k: int = 3) -> List[Tuple[Dict[str, Any], str, str]]:
    """Filed documents that share a container, bill or reference number with
    this one (a carrier's bill and the order's customs entry), with where staff
    filed them. A/B on the gate's 120 unsure filings, 2026-10-25: 88 vs 87,
    the one change a Tumalo bill moved into staff's subfolder, none worse."""
    import time
    from services import order_flow_service as OF
    if not _NUM or time.time() - _NUM["at"] > NUM_SECONDS:
        known = await OF._known_orders(db)
        mem = [m async for m in db.document_memory.find({"folder": {"$ne": ""}, "text": {"$ne": ""}},
                                                        {"_id": 0, "item_id": 1, "folder": 1, "source": 1, "created": 1, "text": 1})]

        def build() -> Dict[str, List[Tuple[str, str]]]:
            # reading numbers out of every filed text is CPU work: off the event loop
            idx: Dict[str, List[Tuple[str, str]]] = {}
            for m in mem:
                if m.get("source") == "sharepoint_ap" and not m["folder"].lower().startswith("temp folder/"):
                    continue
                for t in OF._clean(OF.tokens(m["text"]), known):
                    if re.search(r"[A-Z]", t) or len(t) >= 10:
                        idx.setdefault(t, []).append((str(m.get("created") or ""), m["item_id"]))
            return idx
        idx = await asyncio.to_thread(build)
        _NUM.clear()
        _NUM.update(at=time.time(), idx=idx, known=known)
    m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1}) or {}
    out: List[Tuple[Dict[str, Any], str, str]] = []
    for t in sorted(OF._clean(OF.tokens(m.get("text") or ""), _NUM["known"])):
        hits = [h for h in _NUM["idx"].get(t, ()) if h[0] < before and h[1] != d.get("id")]
        if not hits or len(hits) > 6:      # a number on many documents identifies none of them
            continue
        for _, iid in hits[-2:]:
            if iid in seen:
                continue
            h = await db.document_memory.find_one({"item_id": iid}, {"_id": 0, "text": 0})
            if h and h.get("folder"):
                out.append((h, _label_of(h["folder"]), await _note(db, h, f"shares number {t} with this document")))
                seen.add(iid)
        if len(out) >= k:
            break
    return out[:k]


async def _examples(db, d: Dict[str, Any], before: str, own_name: str = "") -> List[Tuple[Dict[str, Any], str, str]]:
    """The vendor's latest filed documents and documents that read alike,
    each with its order, so the AI can follow the ones whose order is like
    this one's."""
    from services import document_memory_service as DM
    ex, seen = [], set()
    async for h in db.document_memory.find({"source": "hub", "vendor": d.get("vendor_canonical"), "folder": {"$ne": ""},
                                            "created": {"$lt": before}, "item_id": {"$ne": d.get("id")}},
                                           {"_id": 0, "text": 0}).sort("created", -1).limit(SAME_VENDOR):
        ex.append((h, _label_of(h["folder"]), await _note(db, h, "same vendor, recent")))
        seen.add(h["item_id"])
    flow = (d.get("order_flow") or {}).get("order")
    if flow and not d.get("po_number_clean"):
        # Where staff filed earlier paperwork of the order this document is linked to.
        async for h in db.document_memory.find({"folder": {"$regex": flow}, "created": {"$lt": before}, "item_id": {"$nin": list(seen)}},
                                               {"_id": 0, "text": 0}).sort("created", -1).limit(3):
            ex.append((h, _label_of(h["folder"]), f"earlier paperwork of linked order {flow}"))
            seen.add(h["item_id"])
    m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1}) or {}
    n = 0
    for h in await DM.similar(db, m.get("text") or "", d.get("file_name") or "", k=60, exclude={d.get("id")} | seen):
        if n >= SIMILAR:
            break
        if not h.get("folder") or str(h.get("created") or "") >= before or h["name"] == own_name:
            continue
        if h.get("source") == "sharepoint_ap" and not h["folder"].lower().startswith("temp folder/"):
            continue
        ex.append((h, _label_of(h["folder"]), await _note(db, h, f"reads similar ({h['similarity']:.2f})")))
        n += 1
    try:
        ex = (await _shared(db, d, before, set(seen) | {h["item_id"] for h, _, _ in ex})) + ex
    except Exception as e:
        logger.warning("[AIRouting] shared numbers: %r", e)
    return ex


async def decide(db, d: Dict[str, Any], top3: str, rule_lbl: str, allowed: List[Tuple[str, int]],
                 before: str, own_name: str = "", provider=None, rule_path: str = "") -> Tuple[str, float, str, str]:
    """(label, confidence, why, folder). The label is one of the folders
    staff use, or an order's own folder the rules proposed or staff filed a
    past document in (shown to the AI); folder is how staff spell it."""
    from services.llm_router import get_provider
    prov = provider or get_provider("classification")
    m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1}) or {}
    ex = await _examples(db, d, before, own_name)
    ef = d.get("extracted_fields") or {}
    lines = [str(e.get("description") or "")[:70] for e in (ef.get("line_items") or [])[:5]]
    po = str(d.get("po_number_clean") or "").strip().upper()
    flow = d.get("order_flow") or {}
    flow_line = ""
    if not po and flow.get("order"):
        flow_line = (f"\nNo order number on the document, but its {flow.get('via')} is also on the paperwork of order(s) "
                     f"{', '.join(flow.get('orders') or [flow['order']])} (learned link): {await order_facts(db, flow['order'])}")
    user = (f"Document:\nFile: {d.get('file_name')}\nEmail subject: {d.get('email_subject')}\nVendor: {d.get('vendor_canonical') or d.get('vendor_raw')}\n"
            f"Hub type: {d.get('document_type')}  PO/order: {po or '-'}  International flag: {d.get('is_international')}  Amount: {d.get('amount_float')}\n"
            f"Lines: {lines}\nFirst text: {(m.get('text') or '')[:500]}\n\n"
            f"Order in Business Central: {await order_facts(db, po)}{flow_line}\n\n"
            f"How staff file this vendor: {await vendor_habits(db, d.get('vendor_canonical'))}\n"
            f"Model trained on staff's filings, most likely: {top3}\nHand-written rules propose: {rule_lbl}\n\n"
            "Folders staff use (count): " + ", ".join(f"{c} ({n})" for c, n in allowed[:45]) + "\n\n"
            "Past documents and where staff filed them:\n"
            + ("\n".join(f"- \"{h['name']}\" (vendor {h.get('vendor') or '?'}, {why}) -> {l}" for h, l, why in ex) or "(none)"))
    raw = await asyncio.wait_for(prov.complete(SYSTEM, user, f"ai-routing-{d.get('id')}", expect_json=True), 60)
    j = raw if isinstance(raw, dict) else json.loads(re.search(r"\{.*\}", str(getattr(raw, "content", raw)), re.S).group(0))
    lbl = str(j.get("folder") or "").strip().lower()
    seen = {_label_of(h["folder"]): _folder_of(h["folder"]) for h, _, _ in ex}
    if rule_lbl and rule_path:
        seen[rule_lbl] = _folder_of(rule_path)
    if lbl not in {c for c, _ in allowed} and lbl not in seen:
        return "", 0.0, "not a folder staff use", ""
    return lbl, float(j.get("confidence") or 0), str(j.get("why") or "")[:200], seen.get(lbl, "")


async def vendor_habits(db, vendor: Any) -> str:
    """How staff file this vendor: lane shares and top folders from their
    filings. The AI routed StraitLink (customs broker) "international"
    because of customs wording, and MOL / Tapi orders to Warehouse, against
    32 / 23 / 13 staff filings that say domestic dropship (2026-11-02)."""
    v = str(vendor or "").upper()
    if not v:
        return "-"
    lane = await db.vendor_lane_profiles.find_one({"vendor": v}, {"_id": 0}) or {}
    tops = [x async for x in db.vendor_subfolder_profiles.find({"vendor": v}, {"_id": 0, "top": 1, "n": 1})]
    tops.sort(key=lambda x: -(x.get("n") or 0))
    n = int(lane.get("n_all") or lane.get("n") or 0)
    if not n and not tops:
        return "no staff filings yet"
    parts = []
    if n:
        parts.append(f"{n} filings: international {lane.get('intl_share', 0):.0%}, warehouse {lane.get('warehouse_share', 0):.0%}, "
                     f"S&H {lane.get('sh_share', 0):.0%}")
    if tops:
        parts.append("top folders " + ", ".join(f"{t.get('top')} ({t.get('n')})" for t in tops[:4]))
    return "; ".join(parts)


def _view(m: Dict[str, Any], d: Dict[str, Any], rule_path: str):
    from services.folder_learning_service import tokens, _matrix, _probs
    P = _probs(_matrix([tokens(d, rule_path)], m["_fi"]), m["_W"])[0]
    order = P.argsort()[::-1]
    return m["classes"][order[0]], float(P[order[0]]), ", ".join(f"{m['classes'][k]} ({P[k]:.0%})" for k in order[:3])


async def route(db, d: Dict[str, Any], rule_path: str) -> Optional[Tuple[str, float, str, str]]:
    """(path, confidence, label, why) when the AI decides this document's
    folder: AI routing on, and the learned model unsure."""
    if not AI_ROUTING or not d.get("id"):
        return None
    st = await db.folder_model.find_one({"_id": "ai_routing"}, {"_id": 0, "on": 1}) or {}
    if not st.get("on"):
        return None
    from services.folder_learning_service import load, _second
    m = await load(db)
    if "_W" not in m:
        return None
    dd = d
    lbl, p, top3 = _view(m, dd, rule_path)
    if p >= UNSURE:
        return None
    cached = d.get("ai_routing") or {}
    flow = (d.get("order_flow") or {}).get("order")
    if cached.get("rule_path") == rule_path and cached.get("v") == 6 and cached.get("flow") == flow:
        lbl_ai, conf, why, folder = (cached.get("label") or "", cached.get("confidence") or 0.0,
                                     cached.get("why") or "", cached.get("folder") or "")
    else:
        allowed = (await db.folder_model.find_one({"_id": "ai_routing"}, {"_id": 0, "allowed": 1}) or {}).get("allowed") or []
        try:
            lbl_ai, conf, why, folder = await decide(db, dd, top3, _second(rule_path), [tuple(a) for a in allowed],
                                                     before=_now(), rule_path=rule_path)
        except Exception as e:
            logger.warning("[AIRouting] %s: %r", d.get("id"), e)
            return None
        await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"ai_routing": {
            "rule_path": rule_path, "label": lbl_ai, "confidence": conf, "why": why, "folder": folder,
            "model_top": top3, "at": _now(), "v": 6, "flow": flow}}})
    if not lbl_ai:
        return None
    top, sub = m["names"].get(lbl_ai) or (None, None)
    if not top and folder:
        top, _, sub = folder.partition("/")
        sub = sub or None
    if not top:
        return None
    from services.folder_routing_service import _top_defaults
    t = (await _top_defaults(db)).get(top.lower())
    base = t["top"] if t else top
    return base + ("/" + sub if sub else ""), conf, lbl_ai, why


async def evaluate(db, force: bool = False) -> Dict[str, Any]:
    """Replay the latest unsure filings (model trained on the filings before
    them) and keep the AI on only while it beats current routing there."""
    if not AI_ROUTING:
        return {"disabled": True}
    st = await db.folder_model.find_one({"_id": "ai_routing"}) or {}
    if not force and st.get("evaluated_at") and st["evaluated_at"] > (datetime.now(timezone.utc) - timedelta(hours=EVAL_HOURS)).isoformat():
        return {"skipped": "evaluated " + st["evaluated_at"]}
    from services import folder_learning_service as FL
    from services.folder_routing_service import route_with_feedback
    from services.llm_router import get_provider
    fil = {}
    # Every folder staff put the document in: a combined PDF filed to two
    # folders, or one staff moved, kept only the filing read last, so the
    # AI was graded wrong on 120760OBG (Warehouse / B&B and Dropship /
    # Dunnage) and Tumalo 0315575 (2026-11-02).
    staff_labels = collections.defaultdict(set)
    async for f in db.folder_filings.find({}):
        if f.get("hub_doc_id") and f.get("top"):
            fil[f["hub_doc_id"]] = f
            staff_labels[f["hub_doc_id"]].add(FL.label(f))
    staff_roots = {k: {v.split("/")[0] for v in vs} for k, vs in staff_labels.items()}
    data = []
    async for d in db.hub_documents.find({"id": {"$in": list(fil)}}, {"_id": 0, "file_content_b64": 0}):
        f = fil[d["id"]]
        dd = dict(d)
        dd.pop("bc_link", None)
        dd.pop("bc_credit_of", None)
        dd.pop("ai_routing", None)
        # Routed without PDF text, as before 2026-11-01: this fetch never carried
        # the base64 copy, and folder routing's _pdf_text now reads the uploads
        # volume -- here that would parse a PDF per document and move the numbers.
        dd["_pdf_text"] = ""
        try:
            rule = (await route_with_feedback(dd, is_international=bool(dd.get("is_international")), learned=False,
                                              ai=False))[0] or ""
        except Exception:
            rule = ""
        data.append((str(f.get("filed_at") or f.get("created_at")), FL.tokens(dd, rule), FL.label(f), FL._second(rule), f, dd))
    data.sort(key=lambda x: x[0])
    if len(data) < 500:
        return {"skipped": f"only {len(data)} filings"}
    cut = int(len(data) * EVAL_CUT)
    tr, te = data[:cut], data[cut:]
    classes = sorted({x[2] for x in tr})
    ci = {c: k for k, c in enumerate(classes)}
    fi = FL._vocab([x[1] for x in tr])
    W = FL._fit(FL._matrix([x[1] for x in tr], fi), [ci[x[2]] for x in tr], len(classes))
    P = FL._probs(FL._matrix([x[1] for x in te], fi), W)
    gate = (await db.folder_model.find_one({"_id": "current"}, {"gate": 1}) or {}).get("gate") or {}
    th = gate.get("threshold") or 0.5
    counts = collections.Counter(x[2] for x in tr)
    allowed = [(c, n) for c, n in counts.most_common() if n >= 3]
    names = {c for c, _ in allowed}
    prov = get_provider("classification")
    r = collections.Counter()
    rows = []
    cal = []
    unsure = [i for i in range(len(te)) if float(P[i].max()) < UNSURE][-EVAL_MAX:]
    # Three AI calls at a time, each worker still pausing 2 s between its
    # calls: one at a time this step took 713 s of a 30-minute cycle
    # (2026-11-03). Tallied below in the original order, so results match.
    sem = asyncio.Semaphore(3)

    async def _one(i):
        when, toks, truth, rule_lbl, f, d = te[i]
        order = P[i].argsort()[::-1]
        lbl, p = classes[order[0]], float(P[i][order[0]])
        cur = lbl if FL._takes(lbl, p, th, rule_lbl) else rule_lbl
        top3 = ", ".join(f"{classes[k]} ({P[i][k]:.0%})" for k in order[:3])
        async with sem:
            try:
                ai, conf, why, _ = await decide(db, d, top3, rule_lbl, allowed, before=str(d.get("created_utc") or ""),
                                                own_name=str(f.get("_id") or "").rsplit("/", 1)[-1], provider=prov)
            except Exception:
                ai, conf, why = "", 0.0, "error"
            await asyncio.sleep(2)
        return truth, rule_lbl, f, d, cur, ai, conf, why

    answers = await asyncio.gather(*[_one(i) for i in unsure])
    for truth, rule_lbl, f, d, cur, ai, conf, why in answers:
        did = str(d.get("id") or "")
        ok_labels = staff_labels.get(did) or {truth}
        ok_roots = staff_roots.get(did) or {truth.split("/")[0]}
        r["n"] += 1
        r["current_right"] += cur in ok_labels
        r["ai_right"] += (ai or cur) in ok_labels
        cal.append((float(conf or 0), bool(ai), (ai or "").split("/")[0] in ok_roots, (ai or "").split("/")[0],
                    str(d.get("id") or ""), bool(ai) and (ai or "").split("/")[0] == (rule_lbl or "").split("/")[0]))
        if len(rows) < 15 and ai and ai != cur:
            rows.append({"file": d.get("file_name"), "staff": truth, "current": cur, "ai": ai, "why": why})
    on = r["n"] >= MIN_N and r["ai_right"] >= r["current_right"] + max(2, round(MIN_GAIN * r["n"]))
    # How often the AI's top folder matches staff's at each confidence: AP
    # stages trust an AI-routed document only at a confidence where staff's
    # own unsure filings show it reliable (before this, every AI-routed
    # document sat in Needs staff as an unmeasured path - 13 of 30 on
    # 2026-10-26, most at 0.97-0.99).
    from services.ap_stage_service import RELIABLE_MIN_N, RELIABLE_PCT

    def _calibrate(rows):
        calibration, reliable_conf = {}, None
        for t in (0.99, 0.97, 0.95, 0.9, 0.85, 0.8):
            hit = [ok for c, has, ok, *_ in rows if has and c >= t]
            pct = round(100 * sum(hit) / len(hit), 1) if hit else None
            calibration[str(t)] = {"n": len(hit), "pct": pct}
            if len(hit) >= RELIABLE_MIN_N and pct >= RELIABLE_PCT:
                reliable_conf = t
            elif reliable_conf is not None:
                break
        return calibration, reliable_conf

    # Pooled with the previous replays (latest answer per document, up to
    # POOL_ROWS): one 120-document replay swung from 86% to 97% at 0.99 on
    # the same day (2026-10-31), and a low one sent every AI-routed document
    # to staff.
    pooled = {x[4]: x for x in (tuple(y) for y in (st.get("cal_rows") or [])) if len(x) in (5, 6)}
    for x in cal:
        pooled.pop(x[4], None)
        pooled[x[4]] = x
    cal = list(pooled.values())[-POOL_ROWS:]

    # Graded again against staff's latest filing: a document staff later
    # moved from a holding folder kept the verdict of the day it was replayed
    # (4 of 32 "misses" on 2026-11-01 had the AI and staff on the same root).
    def _regrade(x):
        roots = staff_roots.get(x[4])
        if not roots:
            return x
        return (x[0], x[1], bool(x[1]) and x[3] in roots, *x[3:])

    cal = [_regrade(x) for x in cal]
    calibration, reliable_conf = _calibrate(cal)
    # Per top folder the AI chose: overall it was 86% right at 0.99
    # (2026-10-31), so every AI-routed document waited for staff - Pretium
    # RMA credits included, where the folder is never in doubt. A folder
    # family the AI is measured reliable on is trusted on its own.
    by_root = {}
    for fam in sorted({x[3] for x in cal if x[1] and x[3]}):
        cb, rc = _calibrate([x for x in cal if x[3] == fam])
        by_root[fam] = {"conf": rc, **(cb.get(str(rc)) if rc else {"n": max((v["n"] for v in cb.values()), default=0)})}
    # Where the AI and the hand-written rules name the same folder family:
    # Pretium RMA credits (AI 0.99, rules "Vendor Credit Memos") waited for
    # staff because the AI's credit-memo family had 2 replayed filings and the
    # vendor 1 (2026-11-01). Measured on its own rows, not assumed.
    agree_calibration, agree_conf = _calibrate([x for x in cal if len(x) > 5 and x[5]])
    res = {"evaluated_at": _now(), "on": on, "n": r["n"], "ai_right": r["ai_right"], "current_right": r["current_right"],
           "calibration": calibration, "reliable_conf": reliable_conf, "by_folder": by_root, "cal_rows": [list(x) for x in cal],
           "agree_calibration": agree_calibration, "agree_conf": agree_conf,
           "unsure_below": UNSURE, "test_from": te[0][0][:10], "allowed": allowed, "examples": rows}
    await db.folder_model.update_one({"_id": "ai_routing"}, {"$set": res}, upsert=True)
    return {k: v for k, v in res.items() if k not in ("allowed", "examples", "cal_rows")}
