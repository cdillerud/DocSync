"""Will AP enter this document? Learned from what AP actually entered.

Label: an AP-mailbox document older than LABEL_AGE_DAYS is "entered" when AP
has a BC purchase invoice for it (its BC link, or the vendor + invoice
number in AP's harvested BC entries - copies of one invoice all count),
else "not entered". Features are generic: words of the subject, file name,
sender domain, vendor, extracted line descriptions, the document type the
classifier gave, and whether a number / amount / PO were read.

Logistic regression (plain Python SGD), retrained daily; the cut-off below
which a document is filed as "no action" is chosen on held-out documents so
that at most MAX_MISS of the documents under it were in fact entered.

Rule retirement: each hand-written document-type rule (statements,
remittances, notices, ...) is checked against the model on held-out
documents; a rule is retired when the model already files >= COVER of what
the rule catches. Retired rules are skipped by ap_stage_service.
"""
import logging
import math
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

DISPOSITION_MODEL = True
LABEL_AGE_DAYS = 30
MAX_MISS = 0.01
MIN_UNDER = 50
COVER = 0.95
RETRAIN_HOURS = 20
EPOCHS, LR, L2 = 8, 0.1, 1e-6

_STATE: Dict[str, Any] = {}


def _nz(x) -> str:
    return re.sub(r"^0+", "", re.sub(r"[^A-Z0-9]", "", str(x or "").upper()))


def _words(s, p: str) -> List[str]:
    out = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9&.\-]*", str(s or "")):
        w = w.upper().strip(".-")
        if len(w) < 2:
            continue
        out.append(p + (re.sub(r"\d", "9", w) if re.search(r"\d", w) else w))
    return out


def features(d: Dict[str, Any]) -> Set[str]:
    ef = d.get("extracted_fields") or {}
    f = ["bias"]
    f += _words(d.get("email_subject"), "s:") + _words(d.get("file_name"), "f:")
    m = re.search(r"@([\w.-]+)", str(d.get("email_sender") or ""))
    if m:
        f.append("d:" + m.group(1).lower())
    f += ["v:" + str(d.get("vendor_canonical")), "dt:" + str(d.get("doc_type")), "dty:" + str(d.get("document_type"))]
    a = d.get("amount_float")
    try:
        a = float(a) if a not in (None, "") else None
    except (TypeError, ValueError):
        a = None
    f.append("amt:" + ("none" if a is None else "zero" if not a else "neg" if a < 0 else "pos"))
    f.append("inv:" + ("y" if d.get("invoice_number_clean") else "n"))
    f.append("po:" + ("y" if d.get("po_number_clean") else "n"))
    f.append("piece:" + ("y" if d.get("batch_parent_id") else "n"))
    li = ef.get("line_items") or []
    f.append("nl:" + str(min(len(li), 6)))
    for e in li[:6]:
        f += _words(e.get("description"), "l:")[:8]
    f += _words(d.get("vendor_raw"), "vr:")
    return set(f)


def _p(w: Dict[str, float], fs: Set[str]) -> float:
    z = sum(w.get(x, 0.0) for x in fs)
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def _windows(n: str, k: int = 8) -> Set[str]:
    return {n[i:i + k] for i in range(len(n) - k + 1)} if len(n) >= k else set()


async def _labeled(db) -> List[Any]:
    """Entered = AP has a BC invoice or credit memo for it. AP often uses its
    own number (Interstate parking "MN2174-000115 261017", Happy Ann
    "C26X207020" for PI26X207020), so besides the number a same-vendor entry
    of the same amount near the document's date, or a number sharing 8+
    characters, counts."""
    keys, wins = set(), set()
    by_vendor: Dict[str, List[Any]] = {}
    async def add(v, num, amt, date):
        n = _nz(num)
        if n:
            keys.add((v, n))
            keys.add((None, n))
            for x in _windows(n):
                wins.add((v, x))
        try:
            a = round(abs(float(amt)), 2)
        except (TypeError, ValueError):
            a = None
        by_vendor.setdefault(v, []).append((a, str(date or "")[:10]))
    async for r in db.bc_purchase_invoice_lines.find({}, {"_id": 0, "vendorNumber": 1, "vendorInvoiceNumber": 1, "totalAmountExcludingTax": 1, "postingDate": 1}):
        await add(r.get("vendorNumber"), r.get("vendorInvoiceNumber"), r.get("totalAmountExcludingTax"), r.get("postingDate"))
    # Credits count too: AP enters them as purchase credit memos.
    async for r in db.bc_purchase_credit_memos.find({}, {"_id": 0, "vendorNumber": 1, "vendorCreditMemoNumber": 1, "totalAmountExcludingTax": 1, "postingDate": 1}):
        await add(r.get("vendorNumber"), r.get("vendorCreditMemoNumber"), r.get("totalAmountExcludingTax"), r.get("postingDate"))
    cut = (datetime.now(timezone.utc) - timedelta(days=LABEL_AGE_DAYS)).isoformat()
    rows = []
    async for d in db.hub_documents.find({"mailbox_category": "AP", "created_utc": {"$lt": cut},
                                          "duplicate_of_document_id": {"$in": [None, ""]}},
                                         {"_id": 0, "file_content_b64": 0, "line_items": 0}):
        rows.append((features(d), 1 if _entered(d, keys, wins, by_vendor) else 0, d))
    return rows


def _entered(d, keys, wins, by_vendor) -> bool:
    if (d.get("bc_link") or {}).get("bc_document_no"):
        return True
    v = d.get("vendor_canonical")
    n = _nz(d.get("invoice_number_clean"))
    if len(n) >= 4 and ((v, n) in keys or (None, n) in keys):
        return True
    if v and any((v, x) in wins for x in _windows(n)):
        return True
    try:
        a = round(abs(float(d.get("amount_float"))), 2)
    except (TypeError, ValueError):
        a = None
    if v and a:
        day = str(d.get("invoice_date") or d.get("created_utc") or "")[:10]
        try:
            d0 = datetime.fromisoformat(day)
        except ValueError:
            d0 = None
        for amt, pd in by_vendor.get(v, []):
            if amt is not None and abs(amt - a) <= 0.01:
                if not d0 or not pd:
                    return True
                try:
                    gap = (datetime.fromisoformat(pd) - d0).days
                except ValueError:
                    return True
                if -15 <= gap <= 120:
                    return True
    return False


def _rules(bc_vendors: Set[str]):
    """The hand-written document-type rules of ap_stage_service, as
    (name, test(d)) - only the ones a model can replace."""
    from services import ap_stage_service as A
    fs = lambda d: f"{d.get('file_name') or ''} {d.get('email_subject') or ''}"
    return [
        ("account_statement", lambda d: not re.search(r"invoice|\binv", str(d.get("file_name") or ""), re.I) and bool(A._ACCOUNT_STATEMENT.search(fs(d)))),
        ("remittance", lambda d: bool(A._REMITTANCE.search(fs(d)))),
        ("open_items_report", lambda d: bool(A._OPEN_ITEMS_REPORT.search(fs(d)))),
        ("certificate", lambda d: bool(A._CERTIFICATE.search(str(d.get("file_name") or "")))),
        ("notice", lambda d: d.get("amount_float") in (None, "", 0, 0.0) and not d.get("invoice_number_clean") and bool(A._NOTICE.search(fs(d)))),
        ("forwarder_backup", lambda d: bool(d.get("vendor_canonical")) and d.get("vendor_canonical") not in bc_vendors
                                        and bool(A._FORWARDER_MAIL.search(str(d.get("email_sender") or "")))),
    ]


async def train(db, force: bool = False) -> Dict[str, Any]:
    if not DISPOSITION_MODEL:
        return {"disabled": True}
    st = await db.disposition_model.find_one({"_id": "current"}, {"weights": 0}) or {}
    if not force and st.get("trained_at") and st["trained_at"] > (datetime.now(timezone.utc) - timedelta(hours=RETRAIN_HOURS)).isoformat():
        return {"skipped": "trained " + st["trained_at"]}
    rows = await _labeled(db)
    if len(rows) < 500:
        return {"skipped": f"only {len(rows)} labeled documents"}
    rnd = random.Random(7)
    rnd.shuffle(rows)
    split = int(len(rows) * 0.8)
    tr, te = rows[:split], rows[split:]
    w: Dict[str, float] = {}
    for _ in range(EPOCHS):
        rnd.shuffle(tr)
        for fs, y, _d in tr:
            g = y - _p(w, fs)
            for x in fs:
                w[x] = w.get(x, 0.0) + LR * (g - L2 * w.get(x, 0.0))
    scored = sorted(((_p(w, fs), y, d) for fs, y, d in te), key=lambda r: r[0])
    pos = [p for p, y, _ in scored if y]
    neg = [p for p, y, _ in scored if not y]
    import bisect
    ns = sorted(neg)
    auc = sum(bisect.bisect_left(ns, p) for p in pos) / max(len(pos) * len(neg), 1)
    th = 0.0
    for cand in (0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2):
        under = [y for p, y, _ in scored if p < cand]
        if len(under) >= MIN_UNDER and sum(under) / len(under) <= MAX_MISS:
            th = cand
    under = [y for p, y, _ in scored if p < th]
    # Which hand-written rules the model already covers (held-out documents).
    rules = {}
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no", {"blocked": {"$ne": True}}))
    for name, test in _rules(bc_vendors):
        hit = [(p, y) for p, y, d in scored if not (d.get("bc_link") or {}).get("bc_document_no") and test(d)]
        if not hit:
            rules[name] = {"flagged": 0, "retired": False}
            continue
        covered = sum(1 for p, _ in hit if p < th)
        # And every document the rule catches today (last 60 days, not in BC):
        # the model must already file all of them before the rule goes.
        since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        live = live_cov = 0
        async for d in db.hub_documents.find({"mailbox_category": "AP", "created_utc": {"$gte": since},
                                              "bc_link.bc_document_no": {"$exists": False}},
                                             {"_id": 0, "file_content_b64": 0, "line_items": 0}):
            if test(d):
                live += 1
                live_cov += _p(w, features(d)) < th
        rules[name] = {"flagged": len(hit), "rule_wrong": sum(y for _, y in hit), "model_covers": covered,
                       "live_flagged": live, "live_model_covers": live_cov,
                       "retired": th > 0 and len(hit) >= 3 and covered / len(hit) >= COVER and live_cov == live}
    now = datetime.now(timezone.utc).isoformat()
    w = {k: round(v, 4) for k, v in w.items() if abs(v) > 1e-3}
    doc = {"_id": "current", "weights": w, "threshold": th, "auc": round(auc, 4), "trained_at": now,
           "train": len(tr), "test": len(te), "under_threshold": len(under), "under_entered": sum(under),
           "rules": rules}
    await db.disposition_model.replace_one({"_id": "current"}, doc, upsert=True)
    _STATE.clear()
    return {k: v for k, v in doc.items() if k != "weights"} | {"features": len(w)}


async def load(db) -> Dict[str, Any]:
    st = await db.disposition_model.find_one({"_id": "current"}, {"trained_at": 1}) or {}
    if st.get("trained_at") and _STATE.get("trained_at") != st["trained_at"]:
        _STATE.clear()
        _STATE.update(await db.disposition_model.find_one({"_id": "current"}) or {})
    return _STATE


def score(model: Dict[str, Any], d: Dict[str, Any]) -> Optional[float]:
    if not DISPOSITION_MODEL or not model.get("weights"):
        return None
    return _p(model["weights"], features(d))


def retired(model: Dict[str, Any]) -> Set[str]:
    return {k for k, v in (model.get("rules") or {}).items() if v.get("retired")}
