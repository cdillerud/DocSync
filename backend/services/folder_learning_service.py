"""
Learned folder routing.

Which Square9 folder (top folder + first subfolder) staff file a document in,
learned from staff's own filings (folder_filings) instead of hand-written
routing rules. The rule router's suggestion is one input among the
document's own evidence (vendor, type, sender domain, subject / file-name /
line words, PO shape), so the model learns from staff where the rules are
right and where staff file differently.

Self-evaluated on time: trained on the older 80% of filings, tested on the
newest 20%. It replaces the rules' subfolder (never the top folder, which
stages and lanes key off) above the confidence where, on that held-out set,
the combined router beats the rules by MARGIN and the documents it takes
over are at least MIN_ACC right; below it the rules decide. Retrained daily on all
filings with the same settings; the threshold comes from the held-out run.
S&H stages and per-order folders are workflow / order facts, never learned.
"""
import collections
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LEARNED_FOLDERS = True
RETRAIN_HOURS = 20
MIN_ACC = 0.80          # right on the held-out documents it takes over (it only acts where it disagrees with the rules)
MARGIN = 0.02           # combined router vs rules, all held-out documents
MIN_COVER = 20          # held-out documents it takes over
ITERS, LR, L2 = 300, 0.5, 1e-4

_STATE: Dict[str, Any] = {}


def _root(p: str) -> str:
    from services.learning_metrics_service import _root as r
    return r(p)


def _second(p: str) -> str:
    from services.learning_metrics_service import _second as s
    return s(p)


def label(f: Dict[str, Any]) -> str:
    top = (f.get("top_l") or f.get("top") or "").strip().lower()
    if top.startswith("s&h"):
        return "s&h"
    sub = (f.get("subpath") or "").strip("/").split("/")[0].strip().lower()
    return top + ("/" + sub if sub else "")


def _fixed(lbl: str) -> bool:
    """Labels the model never moves a document into or out of."""
    sub = lbl.split("/", 1)[1] if "/" in lbl else ""
    return lbl.startswith("s&h") or bool(re.search(r"\d{4,}", sub))


def _takes(lbl: str, p: float, th: float, rule_lbl: str) -> bool:
    """Does the learned subfolder replace the rules'? Only within the top
    folder the rules chose (stages and lanes key off the top folder)."""
    return (p >= th and lbl != rule_lbl and not _fixed(lbl) and not _fixed(rule_lbl)
            and lbl.split("/")[0] == rule_lbl.split("/")[0])


def tokens(d: Dict[str, Any], rule_path: str) -> set:
    ef = d.get("extracted_fields") or {}
    t = {"R1=" + _root(rule_path), "R2=" + _second(rule_path),
         "V=" + str(d.get("vendor_canonical") or "").upper(),
         "T=" + str(d.get("document_type") or d.get("doc_type")),
         "M=" + str(d.get("mailbox_category")),
         "INTL=" + str(bool(d.get("is_international")))}
    snd = str(d.get("email_sender") or "").lower()
    if "@" in snd:
        t.add("D=" + snd.split("@")[-1])
    po = str(d.get("po_number_clean") or "")
    t.add("PO=" + ("none" if not po else ("W" if po.upper().startswith("W") else re.sub(r"\d", "9", po)[:4])))
    for src, pre in ((d.get("email_subject"), "s:"), (d.get("file_name"), "f:")):
        for w in re.findall(r"[a-z]{3,}", str(src or "").lower()):
            t.add(pre + w)
    for li in (ef.get("line_items") or d.get("line_items") or [])[:12]:
        for w in re.findall(r"[a-z]{3,}", str(li.get("description") or "").lower()):
            t.add("l:" + w)
    for k in ("freight_direction", "freight_gl_classification"):
        if d.get(k):
            t.add(k + "=" + str(d.get(k))[:30])
    # Who the load is from and to, as the bill names them (Tumalo: shipper
    # "CANPACK, Olyphant PA" / "BALL CORP", consignee "Best Bev"): the
    # carrier's PO alone does not say whose product it hauled. Replay
    # 2026-10-27, 679 held-out filings: 591 -> 597 right, none lost.
    for k, pre in (("shipper", "sh:"), ("consignee", "cn:")):
        v = str(ef.get(k) or "").split(",")[0].lower()
        for w in re.findall(r"[a-z]{3,}", v)[:3]:
            t.add(pre + w)
    return t


def _fit(X, y, n_classes):
    import numpy as np
    W = np.zeros((X.shape[1], n_classes), dtype=np.float32)
    Y = np.eye(n_classes, dtype=np.float32)[y]
    for _ in range(ITERS):
        Z = X @ W
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        W -= LR * (X.T @ (P - Y) / len(y) + L2 * W)
    return W


def _matrix(rows, fi):
    import numpy as np
    m = np.zeros((len(rows), len(fi) + 1), dtype=np.float32)
    for r, ts in enumerate(rows):
        for t in ts:
            k = fi.get(t)
            if k is not None:
                m[r, k] = 1
        m[r, -1] = 1
    return m


def _probs(X, W):
    import numpy as np
    Z = X @ W
    Z -= Z.max(1, keepdims=True)
    P = np.exp(Z)
    return P / P.sum(1, keepdims=True)


def _vocab(rows) -> Dict[str, int]:
    c = collections.Counter(t for ts in rows for t in ts)
    return {t: k for k, t in enumerate(sorted(t for t, n in c.items() if n >= 2))}


async def train(db, force: bool = False) -> Dict[str, Any]:
    if not LEARNED_FOLDERS:
        return {"disabled": True}
    st = await db.folder_model.find_one({"_id": "current"}, {"trained_at": 1}) or {}
    if not force and st.get("trained_at") and st["trained_at"] > (datetime.now(timezone.utc) - timedelta(hours=RETRAIN_HOURS)).isoformat():
        return {"skipped": "trained " + st["trained_at"]}
    from services.folder_routing_service import route_with_feedback
    fil = {}
    async for f in db.folder_filings.find({}, {"_id": 0}):
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
        data.append((str(f.get("filed_at") or f.get("created_at")), tokens(d, rule), label(f), _second(rule), f))
    data.sort(key=lambda x: x[0])
    if len(data) < 500:
        return {"skipped": f"only {len(data)} filings"}
    cut = int(len(data) * 0.8)
    tr, te = data[:cut], data[cut:]
    classes = sorted({x[2] for x in tr})
    ci = {c: k for k, c in enumerate(classes)}
    fi = _vocab([x[1] for x in tr])
    W = _fit(_matrix([x[1] for x in tr], fi), [ci[x[2]] for x in tr], len(classes))
    P = _probs(_matrix([x[1] for x in te], fi), W)
    pred = [classes[k] for k in P.argmax(1)]
    conf = P.max(1)
    # Threshold: the confidence at which the combined router (learned
    # subfolder where it takes over, rules elsewhere) is most often right on
    # the held-out filings; on only if that beats the rules by MARGIN and the
    # documents it takes over are at least MIN_ACC right.
    n = len(te)
    rules_ok = sum(te[i][3] == te[i][2] for i in range(n))
    best, scan = None, []
    for th in [x / 100 for x in range(30, 100, 5)]:
        take = [i for i in range(n) if _takes(pred[i], float(conf[i]), th, te[i][3])]
        if not take:
            break
        acc = sum(pred[i] == te[i][2] for i in take) / len(take)
        comb = (rules_ok - sum(te[i][3] == te[i][2] for i in take) + sum(pred[i] == te[i][2] for i in take)) / n
        scan.append((th, len(take), round(acc, 3), round(sum(te[i][3] == te[i][2] for i in take) / len(take), 3), round(comb, 3)))
        if len(take) < MIN_COVER:
            continue
        if acc >= MIN_ACC and comb >= rules_ok / n + MARGIN and (best is None or comb > best["combined_acc"]):
            best = {"threshold": th, "takes_over": len(take), "learned_acc_on_those": round(acc, 3),
                    "rules_acc_on_those": round(sum(te[i][3] == te[i][2] for i in take) / len(take), 3),
                    "combined_acc": round(comb, 3), "rules_acc": round(rules_ok / n, 3)}
    held = {"test": n, "test_from": te[0][0][:10], "scan (threshold, takes over, learned acc, rules acc, combined)": scan,
            "learned_sub": round(sum(pred[i] == te[i][2] for i in range(n)) / n, 3),
            "rules_sub": round(sum(te[i][3] == te[i][2] for i in range(n)) / n, 3),
            "learned_top": round(sum(pred[i].split("/")[0] == te[i][2].split("/")[0] for i in range(n)) / n, 3),
            "rules_top": round(sum(_root(te[i][3]) == te[i][2].split("/")[0] for i in range(n)) / n, 3)}
    # Deploy on all filings, same settings; real-case folder names per label.
    classes = sorted({x[2] for x in data})
    ci = {c: k for k, c in enumerate(classes)}
    fi = _vocab([x[1] for x in data])
    W = _fit(_matrix([x[1] for x in data], fi), [ci[x[2]] for x in data], len(classes))
    names: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for x in data:
        f = x[4]
        sub = (f.get("subpath") or "").strip("/").split("/")[0].strip()
        names[x[2]][(f.get("top") or "", sub)] += 1
    now = datetime.now(timezone.utc).isoformat()
    doc = {"_id": "current", "trained_at": now, "filings": len(data), "classes": classes,
           "names": {c: list(names[c].most_common(1)[0][0]) for c in classes},
           "features": sorted(fi, key=fi.get), "weights": W.round(4).tolist(),
           "held_out": held, "gate": best, "enabled": best is not None}
    await db.folder_model.replace_one({"_id": "current"}, doc, upsert=True)
    _STATE.clear()
    return {"filings": len(data), "classes": len(classes), "held_out": held, "gate": best}


async def load(db) -> Dict[str, Any]:
    if not _STATE or _STATE.get("_loaded_at", "") < (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat():
        m = await db.folder_model.find_one({"_id": "current"}) or {}
        _STATE.clear()
        _STATE.update(m)
        if m.get("features"):
            import numpy as np
            _STATE["_fi"] = {t: k for k, t in enumerate(m["features"])}
            _STATE["_W"] = np.array(m["weights"], dtype=np.float32)
        _STATE["_loaded_at"] = datetime.now(timezone.utc).isoformat()
    return _STATE


async def override(db, doc: Dict[str, Any], rule_path: str) -> Optional[Tuple[str, float, str]]:
    """(path, confidence, label) when the learned folder replaces the rules'."""
    if not LEARNED_FOLDERS:
        return None
    m = await load(db)
    if not m.get("enabled") or "_W" not in m:
        return None
    rule_lbl = _second(rule_path)
    if _fixed(rule_lbl):
        return None
    P = _probs(_matrix([tokens(doc, rule_path)], m["_fi"]), m["_W"])[0]
    k = int(P.argmax())
    lbl, p = m["classes"][k], float(P[k])
    if not _takes(lbl, p, m["gate"]["threshold"], rule_lbl):
        return None
    top, sub = m["names"].get(lbl) or (None, None)
    if not top:
        return None
    from services.folder_routing_service import _top_defaults
    t = (await _top_defaults(db)).get(top.lower())
    base = t["top"] if t else top
    return base + ("/" + sub if sub else ""), p, lbl
