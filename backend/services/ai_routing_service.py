"""The AI decides the folder where the learned folder model is unsure.

Routing is the rules' folder, then the learned subfolder where the model
trained on staff's filings is confident (folder_learning_service). Where
that model is unsure (top choice under UNSURE), the AI decides instead:
it sees the document, what Business Central says about its order (whose
goods were received on it), the model's top choices with probabilities,
the rules' proposal, and past documents like it with where staff filed
each (document_memory: the vendor's latest filings and documents that read
alike). Added on top of the rules and the model, not in place of them.

Replay on filings after the model's training period (2026-10-24, 648
filings, 51 unsure): current routing 52.9% right on the unsure ones, the
AI 62.7%; all 648: 86.3% -> 87.0%.

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
EVAL_MAX = 60           # unsure filings replayed per evaluation (one AI call each)
MIN_N = 30
MIN_GAIN = 2            # documents the AI must get right beyond current routing
EXAMPLES = 8

SYSTEM = ("You route Gamer Packaging's accounts-payable documents to the SharePoint folder staff would file them in. "
          "You see the document, what the Hub's order lookup in Business Central says about its order, the folders a model "
          "trained on staff's past filings thinks most likely (with probabilities), the folder the hand-written rules propose, "
          "and past documents like this one with the folder staff filed each in. Decide where staff would file it. "
          "Answer JSON only: {\"folder\": \"<one of the listed folders, exactly>\", \"confidence\": 0-1, \"why\": \"<short>\"}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def order_facts(db, po: str) -> str:
    if not po:
        return "no order number on the document"
    out = []
    async for r in db.bc_purchase_receipts.find({"orderNumber": po}, {"_id": 0, "vendorNumber": 1, "postingDate": 1,
                                                                      "purchaseReceiptLines": 1}).limit(5):
        items = [str(l.get("description") or "")[:50] for l in (r.get("purchaseReceiptLines") or []) if l.get("lineObjectNumber")][:3]
        out.append(f"received from {r.get('vendorNumber')} on {r.get('postingDate')}: {items}")
    so = await db.bc_sales_orders.find_one({"number": po}, {"_id": 0, "customerName": 1, "customerNumber": 1, "shipToName": 1})
    if so:
        out.append(f"sales order for {so.get('customerName') or so.get('customerNumber')} ship to {so.get('shipToName')}")
    return "; ".join(out) or f"order {po}: nothing received in BC yet"


def _label_of(folder: str) -> str:
    from services.folder_learning_service import label
    fo = folder[12:] if folder.lower().startswith("temp folder/") else folder
    parts = [p for p in fo.split("/") if p]
    return label({"top": parts[0] if parts else "", "subpath": "/".join(parts[1:])})


async def _examples(db, d: Dict[str, Any], before: str, own_name: str = "") -> List[Tuple[Dict[str, Any], str, str]]:
    from services import document_memory_service as DM
    ex, seen = [], set()
    async for h in db.document_memory.find({"source": "hub", "vendor": d.get("vendor_canonical"), "folder": {"$ne": ""},
                                            "created": {"$lt": before}, "item_id": {"$ne": d.get("id")}},
                                           {"_id": 0, "text": 0}).sort("created", -1).limit(4):
        ex.append((h, _label_of(h["folder"]), "same vendor, most recent"))
        seen.add(h["item_id"])
    m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1}) or {}
    for h in await DM.similar(db, m.get("text") or "", d.get("file_name") or "", k=60, exclude={d.get("id")} | seen):
        if len(ex) >= EXAMPLES:
            break
        if not h.get("folder") or str(h.get("created") or "") >= before or h["name"] == own_name:
            continue
        if h.get("source") == "sharepoint_ap" and not h["folder"].lower().startswith("temp folder/"):
            continue
        ex.append((h, _label_of(h["folder"]), f"reads similar ({h['similarity']:.2f})"))
    return ex


async def decide(db, d: Dict[str, Any], top3: str, rule_lbl: str, allowed: List[Tuple[str, int]],
                 before: str, own_name: str = "", provider=None) -> Tuple[str, float, str]:
    from services.llm_router import get_provider
    prov = provider or get_provider("classification")
    m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1}) or {}
    ex = await _examples(db, d, before, own_name)
    ef = d.get("extracted_fields") or {}
    lines = [str(e.get("description") or "")[:70] for e in (ef.get("line_items") or [])[:5]]
    po = str(d.get("po_number_clean") or "").strip().upper()
    user = (f"Document:\nFile: {d.get('file_name')}\nEmail subject: {d.get('email_subject')}\nVendor: {d.get('vendor_canonical') or d.get('vendor_raw')}\n"
            f"Hub type: {d.get('document_type')}  PO/order: {po or '-'}  International flag: {d.get('is_international')}  Amount: {d.get('amount_float')}\n"
            f"Lines: {lines}\nFirst text: {(m.get('text') or '')[:500]}\n\n"
            f"Order in Business Central: {await order_facts(db, po)}\n\n"
            f"Model trained on staff's filings, most likely: {top3}\nHand-written rules propose: {rule_lbl}\n\n"
            "Folders staff use (count): " + ", ".join(f"{c} ({n})" for c, n in allowed[:45]) + "\n\n"
            "Past documents and where staff filed them:\n"
            + ("\n".join(f"- \"{h['name']}\" (vendor {h.get('vendor') or '?'}, {why}) -> {l}" for h, l, why in ex) or "(none)"))
    raw = await asyncio.wait_for(prov.complete(SYSTEM, user, f"ai-routing-{d.get('id')}", expect_json=True), 60)
    j = raw if isinstance(raw, dict) else json.loads(re.search(r"\{.*\}", str(getattr(raw, "content", raw)), re.S).group(0))
    lbl = str(j.get("folder") or "").strip().lower()
    if lbl not in {c for c, _ in allowed}:
        return "", 0.0, "not a folder staff use"
    return lbl, float(j.get("confidence") or 0), str(j.get("why") or "")[:200]


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
    if cached.get("rule_path") == rule_path and cached.get("label"):
        lbl_ai, conf, why = cached["label"], cached.get("confidence") or 0.0, cached.get("why") or ""
    else:
        allowed = (await db.folder_model.find_one({"_id": "ai_routing"}, {"_id": 0, "allowed": 1}) or {}).get("allowed") or []
        try:
            lbl_ai, conf, why = await decide(db, dd, top3, _second(rule_path), [tuple(a) for a in allowed], before=_now())
        except Exception as e:
            logger.warning("[AIRouting] %s: %r", d.get("id"), e)
            return None
        await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"ai_routing": {
            "rule_path": rule_path, "label": lbl_ai, "confidence": conf, "why": why, "model_top": top3, "at": _now()}}})
    if not lbl_ai:
        return None
    top, sub = m["names"].get(lbl_ai) or (None, None)
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
    async for f in db.folder_filings.find({}):
        if f.get("hub_doc_id") and f.get("top"):
            fil[f["hub_doc_id"]] = f
    data = []
    async for d in db.hub_documents.find({"id": {"$in": list(fil)}}, {"_id": 0, "file_content_b64": 0}):
        f = fil[d["id"]]
        dd = dict(d)
        dd.pop("bc_link", None)
        dd.pop("bc_credit_of", None)
        try:
            rule = (await route_with_feedback(dd, is_international=bool(dd.get("is_international")), learned=False))[0] or ""
        except Exception:
            rule = ""
        data.append((str(f.get("filed_at") or f.get("created_at")), FL.tokens(dd, rule), FL.label(f), FL._second(rule), f, dd))
    data.sort(key=lambda x: x[0])
    if len(data) < 500:
        return {"skipped": f"only {len(data)} filings"}
    cut = int(len(data) * 0.8)
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
    unsure = [i for i in range(len(te)) if float(P[i].max()) < UNSURE][-EVAL_MAX:]
    for i in unsure:
        when, toks, truth, rule_lbl, f, d = te[i]
        order = P[i].argsort()[::-1]
        lbl, p = classes[order[0]], float(P[i][order[0]])
        cur = lbl if FL._takes(lbl, p, th, rule_lbl) else rule_lbl
        top3 = ", ".join(f"{classes[k]} ({P[i][k]:.0%})" for k in order[:3])
        try:
            ai, conf, why = await decide(db, d, top3, rule_lbl, allowed, before=str(d.get("created_utc") or ""),
                                         own_name=str(f.get("_id") or "").rsplit("/", 1)[-1], provider=prov)
        except Exception:
            ai, conf, why = "", 0.0, "error"
        await asyncio.sleep(2)
        r["n"] += 1
        r["current_right"] += cur == truth
        r["ai_right"] += (ai or cur) == truth
        if len(rows) < 15 and ai and ai != cur:
            rows.append({"file": d.get("file_name"), "staff": truth, "current": cur, "ai": ai, "why": why})
    on = r["n"] >= MIN_N and r["ai_right"] >= r["current_right"] + MIN_GAIN
    res = {"evaluated_at": _now(), "on": on, "n": r["n"], "ai_right": r["ai_right"], "current_right": r["current_right"],
           "unsure_below": UNSURE, "test_from": te[0][0][:10], "allowed": allowed, "examples": rows}
    await db.folder_model.update_one({"_id": "ai_routing"}, {"$set": res}, upsert=True)
    return {k: v for k, v in res.items() if k not in ("allowed", "examples")}
