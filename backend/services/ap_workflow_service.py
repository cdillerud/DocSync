"""AP workflow states that Square9 kept in folder names: holds and approvals.

Square9 staff encode workflow in folders (45 days of filings, 2026-10-06):
"S&H Invoices waiting for approval/Ellie|Andy|Jess to approve",
"S&H Invoices Approved/Amanda to process", "Misc Invoices - need
approval / approved", "Canworks - Hold Until Ship Dates Confirmed", "HOLD
Orders - Long Term", "UPS orders - Holding for Freight", "Issues - Longer
Hold", "Processed Credit Memo - Aaron". The Hub makes these explicit:

* hold:     ap_hold {reason, until, by, at}; released by a person (or
            shown as due once `until` has passed)
* approval: ap_approval {approver, status pending|approved|rejected,
            requested_by, requested_at, decided_by, decided_at, notes}
* people:   ap_people {name, roles [approver, processor], areas} - seeded
            from the Square9 folder names, editable
* every action is appended to ap_workflow_events (audit trail)

Approver suggestion: per vendor, which approver staff filed its S&H
invoices under in Square9 (learned from parity filings), else the most
frequent S&H approver. Nothing here writes outside the Hub database.
"""
import csv
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

APPROVE_FOLDER = re.compile(r"waiting for approval/([A-Za-z]+) to approve", re.I)
PROCESS_FOLDER = re.compile(r"(?:approved/([A-Za-z]+) to process|processed credit memo - ([A-Za-z]+))", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _event(db, doc_id: str, action: str, by: str, **details) -> None:
    await db.ap_workflow_events.insert_one({"document_id": doc_id, "action": action, "by": by or "unknown",
                                            "at": _now(), **details})


async def learn_people_and_approvers(db, csv_paths) -> Dict[str, Any]:
    """Approvers / processors named in Square9 folders, and per-vendor
    approver counts from S&H filings."""
    approvers, processors = Counter(), Counter()
    by_vendor = defaultdict(Counter)
    seen = set()
    for path in csv_paths:
        try:
            rows = list(csv.DictReader(open(path)))
        except FileNotFoundError:
            continue
        for r in rows:
            p = r.get("square9_parent_path") or ""
            if not p or r.get("hub_doc_id") in seen:
                continue
            seen.add(r.get("hub_doc_id"))
            m = APPROVE_FOLDER.search(p)
            if m:
                name = m.group(1).title()
                approvers[name] += 1
                d = await db.hub_documents.find_one({"id": r.get("hub_doc_id")}, {"_id": 0, "vendor_canonical": 1})
                if d and d.get("vendor_canonical"):
                    by_vendor[str(d["vendor_canonical"]).upper()][name] += 1
            m = PROCESS_FOLDER.search(p)
            if m:
                processors[(m.group(1) or m.group(2)).title()] += 1
    now = _now()
    for name, n in approvers.items():
        await db.ap_people.update_one({"name": name}, {"$addToSet": {"roles": "approver", "areas": "S&H"},
                                                       "$set": {"learned_filings": n, "updated_at": now},
                                                       "$setOnInsert": {"name": name, "active": True, "created_at": now}},
                                      upsert=True)
    for name, n in processors.items():
        await db.ap_people.update_one({"name": name}, {"$addToSet": {"roles": "processor"},
                                                       "$set": {"updated_at": now},
                                                       "$setOnInsert": {"name": name, "active": True, "created_at": now}},
                                      upsert=True)
    for v, c in by_vendor.items():
        await db.ap_approver_rules.update_one({"vendor": v}, {"$set": {"vendor": v, "counts": dict(c),
                                                                        "approver": c.most_common(1)[0][0],
                                                                        "updated_at": now}}, upsert=True)
    return {"approvers": dict(approvers), "processors": dict(processors), "vendors": len(by_vendor)}


async def suggest_approver(db, doc: Dict[str, Any]) -> Optional[str]:
    v = str(doc.get("vendor_canonical") or "").upper()
    if v:
        rule = await db.ap_approver_rules.find_one({"vendor": v}, {"_id": 0, "approver": 1})
        if rule:
            return rule["approver"]
    top = await db.ap_people.find_one({"roles": "approver", "active": {"$ne": False}}, {"_id": 0, "name": 1},
                                      sort=[("learned_filings", -1)])
    return (top or {}).get("name")


async def put_on_hold(db, doc_id: str, reason: str, until: Optional[str], by: str) -> Dict[str, Any]:
    hold = {"reason": reason, "until": until or None, "by": by, "at": _now()}
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {"ap_hold": hold, "ap_stage": "on_hold",
                                                                "ap_stage_updated_at": hold["at"]}})
    await _event(db, doc_id, "hold", by, reason=reason, until=until)
    return hold


async def release_hold(db, doc_id: str, by: str, notes: str = "") -> None:
    await db.hub_documents.update_one({"id": doc_id}, {"$unset": {"ap_hold": ""},
                                                       "$set": {"ap_hold_released": {"by": by, "at": _now(), "notes": notes}}})
    await _event(db, doc_id, "release_hold", by, notes=notes)


TEAMS_APPROVALS_WEBHOOK_ENV = "TEAMS_APPROVALS_WEBHOOK_URL"


def _approval_card(doc: Dict[str, Any], appr: Dict[str, Any]) -> Dict[str, Any]:
    """Adaptive Card for a Teams Workflows webhook: who should approve what."""
    import os
    base = (os.environ.get("APP_PUBLIC_URL") or "https://docsync.gamerpackaging.com").rstrip("/")
    amt = doc.get("amount_float")
    facts = [{"title": "Vendor", "value": str(doc.get("vendor_canonical") or doc.get("vendor_raw") or "?")},
             {"title": "Invoice", "value": str(doc.get("invoice_number_clean") or "?")},
             {"title": "Amount", "value": f"${amt:,.2f}" if isinstance(amt, (int, float)) else "?"},
             {"title": "Requested by", "value": str(appr.get("requested_by") or "?")}]
    if appr.get("round", 1) > 1:
        facts.append({"title": "Round", "value": f"{appr['round']} (resent after rejection)"})
    if appr.get("notes"):
        facts.append({"title": "Notes", "value": str(appr["notes"])[:300]})
    body = [{"type": "TextBlock", "weight": "Bolder", "size": "Medium", "wrap": True,
             "text": f"{appr.get('approver')}: invoice waiting for your approval"},
            {"type": "FactSet", "facts": facts}]
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                    "version": "1.4", "body": body,
                    "actions": [{"type": "Action.OpenUrl", "title": "Open in the Hub",
                                 "url": f"{base}/documents/{doc.get('id')}"}]}}]}


async def notify_approver(db, doc_id: str, appr: Dict[str, Any]) -> Dict[str, Any]:
    """Post the approval request to Teams. Off until the webhook is set;
    never blocks or fails the approval itself."""
    import os
    url = os.environ.get(TEAMS_APPROVALS_WEBHOOK_ENV)
    if not url:
        return {"skipped": f"{TEAMS_APPROVALS_WEBHOOK_ENV} not set"}
    try:
        import httpx
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "vendor_canonical": 1, "vendor_raw": 1,
                                                               "invoice_number_clean": 1, "amount_float": 1}) or {"id": doc_id}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=_approval_card(doc, appr))
        res = {"status": r.status_code}
        if 200 <= r.status_code < 300:
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"ap_approval_notified_at": _now()}})
    except Exception as e:  # noqa: BLE001
        res = {"error": str(e)[:200]}
    await _event(db, doc_id, "notify_teams", "hub", approver=appr.get("approver"), result=res)
    return res


async def notify_waiting(db, days: int = 3, limit: int = 20) -> Dict[str, Any]:
    """Teams card, once, for invoices that went to awaiting approval on
    their own (S&H, "need approval" folder) with a suggested approver."""
    import os
    from datetime import timedelta
    if not os.environ.get(TEAMS_APPROVALS_WEBHOOK_ENV):
        return {"skipped": f"{TEAMS_APPROVALS_WEBHOOK_ENV} not set"}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sent = 0
    async for d in db.hub_documents.find({"ap_stage": "awaiting_approval", "ap_stage_updated_at": {"$gte": since},
                                          "ap_approval_notified_at": {"$exists": False}},
                                         {"_id": 0, "id": 1, "ap_approval": 1, "suggested_approver": 1}).limit(limit):
        appr = dict(d.get("ap_approval") or {})
        appr.setdefault("approver", d.get("suggested_approver"))
        appr.setdefault("requested_by", "the Hub (learned from Square 9 filings)")
        if not appr.get("approver"):
            continue
        res = await notify_approver(db, d["id"], appr)
        sent += 1 if str(res.get("status", "")).startswith("2") else 0
    return {"sent": sent}


async def request_approval(db, doc_id: str, approver: str, by: str, notes: str = "") -> Dict[str, Any]:
    """Ask a person to approve. A decided earlier round (e.g. rejected, then
    fixed) is kept in ap_approval_history and the new round is numbered."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "ap_approval": 1})
    prev = (doc or {}).get("ap_approval") or {}
    appr = {"approver": approver, "status": "pending", "requested_by": by, "requested_at": _now(), "notes": notes,
            "round": int(prev.get("round") or 1) + 1 if prev.get("status") in ("rejected", "approved") else int(prev.get("round") or 1)}
    upd = {"$set": {"ap_approval": appr, "ap_stage": "awaiting_approval", "ap_stage_updated_at": appr["requested_at"]}}
    if prev.get("status") in ("rejected", "approved"):
        upd["$push"] = {"ap_approval_history": prev}
    await db.hub_documents.update_one({"id": doc_id}, upd)
    await _event(db, doc_id, "request_approval", by, approver=approver, notes=notes, round=appr["round"])
    appr["notified"] = await notify_approver(db, doc_id, appr)
    return appr


async def decide_approval(db, doc_id: str, approved: bool, by: str, notes: str = "") -> Dict[str, Any]:
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "ap_approval": 1})
    appr = dict((doc or {}).get("ap_approval") or {})
    appr.update({"status": "approved" if approved else "rejected", "decided_by": by, "decided_at": _now(),
                 "decision_notes": notes})
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {"ap_approval": appr}})
    await _event(db, doc_id, "approve" if approved else "reject", by, notes=notes)
    return appr




async def actor_for(db, user) -> dict:
    """The AP person a signed-in Hub user is.

    Microsoft-signed-in users act as themselves: matched to an AP person by
    a remembered e-mail, else by first name (Square9 folders name people by
    first name: "Ellie to approve"); the link is remembered. Unmatched users
    act under their own display name. The shared admin login (password) is
    not a person: it still picks a name on the page.
    """
    user = user or {}
    email = str(user.get("email") or "").lower()
    if user.get("auth_provider") != "entra" or not email:
        return {"sso": False, "name": "", "email": email}
    person = await db.ap_people.find_one({"email": email}, {"_id": 0})
    if not person:
        first = str(user.get("display_name") or "").split(" ")[0].strip()
        if first:
            import re as _re
            matches = [p async for p in db.ap_people.find(
                {"name": {"$regex": f"^{_re.escape(first)}$", "$options": "i"}, "email": {"$exists": False}}, {"_id": 0})]
            if len(matches) == 1:
                person = matches[0]
                await db.ap_people.update_one({"name": person["name"]}, {"$set": {
                    "email": email, "full_name": user.get("display_name"), "linked_at": _now()}})
    name = person["name"] if person else (user.get("display_name") or email)
    return {"sso": True, "name": name, "email": email, "full_name": user.get("display_name"),
            "person": bool(person), "roles": (person or {}).get("roles", [])}
