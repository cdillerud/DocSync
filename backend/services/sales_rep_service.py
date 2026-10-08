"""Which inside sales rep owns a sales document - one queue per rep.

Customers' POs concentrate in one inside sales mailbox (2026-10-07:
Giovanni -> nhannover 69/70, Horseshoe -> asaumweber 68, Watkins ->
jfulton 22/23, Hearthside -> klundquist 12/12). In order:
  1. a person's assignment: this document, else this customer
     (sales_rep_overrides, set on the Sales Inbox)
  2. the customer's usual rep: the mailbox receiving >= 60% of the
     customer's POs (>= 3 POs)
  3. the mailbox this document arrived in
  4. the BC salesperson on the customer's recent orders, when that person
     is an inside sales rep
  5. unassigned
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

GAMER = "@gamerpackaging.com"


def rep_mailboxes() -> List[str]:
    import os
    return [m.strip().lower() for m in os.environ.get("INSIDE_SALES_PILOT_MAILBOXES", "").split(",") if m.strip()]


def _name(email: str, users: Dict[str, str]) -> str:
    """Microsoft sign-in name, else a name the old sales code recorded for
    this e-mail, else "N. Hannover" from nhannover@."""
    if users.get(email):
        return users[email]
    local = email.split("@")[0]
    return f"{local[:1].upper()}. {local[1:2].upper()}{local[2:]}" if len(local) > 2 else local


async def context(db) -> Dict[str, Any]:
    reps = rep_mailboxes()
    users = {}
    async for x in db.hub_documents.aggregate([
            {"$match": {"assigned_rep_email": {"$in": [r for r in reps] + [r.title() for r in reps]}, "assigned_rep_name": {"$nin": [None, ""]}}},
            {"$group": {"_id": {"$toLower": "$assigned_rep_email"}, "name": {"$first": "$assigned_rep_name"}}}]):
        users[x["_id"]] = x["name"]
    async for u in db.users.find({"email": {"$in": reps}}, {"_id": 0, "email": 1, "display_name": 1}):
        if u.get("display_name"):
            users[str(u["email"]).lower()] = u["display_name"]
    by_cust = defaultdict(Counter)
    async for d in db.hub_documents.find({"sales_link.role": "customer_po", "pilot_mailbox": {"$exists": True}},
                                         {"_id": 0, "pilot_mailbox": 1, "sales_link.bc_customer_no": 1}):
        c = (d.get("sales_link") or {}).get("bc_customer_no")
        if c and d.get("pilot_mailbox"):
            by_cust[c][str(d["pilot_mailbox"]).lower()] += 1
    usual = {}
    for c, cnt in by_cust.items():
        m, k = cnt.most_common(1)[0]
        if k >= 3 and k / sum(cnt.values()) >= 0.6:
            usual[c] = (m, k, sum(cnt.values()))
    sp_email = {s["bc_document_no"]: str(s.get("email") or "").lower()
                async for s in db.bc_reference_cache.find({"bc_entity_type": "salesperson"}, {"_id": 0, "bc_document_no": 1, "email": 1})}
    cust_sp = {}
    async for o in db.bc_sales_orders.find({"salesperson": {"$nin": [None, ""]}}, {"_id": 0, "customer_no": 1, "salesperson": 1}).sort([("order_no", -1)]):
        cust_sp.setdefault(o["customer_no"], o["salesperson"])
    overrides = {(o.get("scope"), o.get("key")): o async for o in db.sales_rep_overrides.find({}, {"_id": 0})}
    return {"reps": reps, "users": users, "usual": usual, "sp_email": sp_email, "cust_sp": cust_sp, "overrides": overrides}


def assign(d: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    cust = (d.get("sales_link") or {}).get("bc_customer_no")
    o = ctx["overrides"].get(("document", d.get("id"))) or (ctx["overrides"].get(("customer", cust)) if cust else None)
    if o:
        email, how = o["rep_email"], f"assigned by {o.get('by_name') or o.get('by') or 'a person'}" + (" for this customer" if o["scope"] == "customer" else "")
    elif cust in ctx["usual"]:
        m, k, n = ctx["usual"][cust]
        email, how = m, f"this customer's usual rep ({k} of {n} POs)"
    elif str(d.get("pilot_mailbox") or "").lower() in ctx["reps"]:
        email, how = str(d["pilot_mailbox"]).lower(), "arrived in this rep's mailbox"
    elif cust and ctx["sp_email"].get(ctx["cust_sp"].get(cust) or "") in ctx["reps"]:
        email, how = ctx["sp_email"][ctx["cust_sp"][cust]], f"BC salesperson {ctx['cust_sp'][cust]} on this customer's orders"
    else:
        return {"email": None, "name": "Unassigned", "how": "no rep found"}
    return {"email": email, "name": _name(email, ctx["users"]), "how": how}


async def set_override(db, scope: str, key: str, rep_email: Optional[str], by: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if not rep_email:
        await db.sales_rep_overrides.delete_one({"scope": scope, "key": key})
        return
    await db.sales_rep_overrides.update_one({"scope": scope, "key": key}, {"$set": {
        "scope": scope, "key": key, "rep_email": rep_email.lower(), "by": by.get("email"),
        "by_name": by.get("display_name"), "at": now}}, upsert=True)

