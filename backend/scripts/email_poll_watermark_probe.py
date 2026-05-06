"""
Read-only diagnostic: probe Microsoft Graph with the EXACT filter the
polling service uses for hub-ap-intake@, and dump the first N messages
returned. Used to diagnose why a watermark stalled at a specific timestamp.

Operator example:
    python /app/scripts/email_poll_watermark_probe.py --top 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import MongoClient


async def main_async(top: int) -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from services.config_service import get_email_token  # type: ignore

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    wm = db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
    print("=== current email_poll_watermark ===")
    print(json.dumps(wm, default=str, indent=2))

    if not wm or not wm.get("last_received_datetime"):
        print("No watermark present — nothing to probe.")
        return 0
    watermark_time = wm["last_received_datetime"]

    user = os.environ["EMAIL_POLLING_USER"]
    token = await get_email_token()
    if not token:
        print("Failed to acquire Graph token.")
        return 1

    params = {
        "$filter": f"receivedDateTime gt {watermark_time}",
        "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments",
        "$top": top,
        "$orderby": "receivedDateTime asc",
    }
    print("\n=== Graph query parameters being used by the live poller ===")
    print(json.dumps(params, indent=2))

    async with httpx.AsyncClient(timeout=60.0) as h:
        r = await h.get(
            f"https://graph.microsoft.com/v1.0/users/{user}/mailFolders/Inbox/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )

    print(f"\n=== Graph response status: {r.status_code} ===")
    if r.status_code != 200:
        print(r.text[:500])
        return 2

    data = r.json()
    msgs = data.get("value", [])
    print(f"messages returned: {len(msgs)}")

    print("\n=== first {} messages (id / receivedDateTime / subject / hasAttachments) ===".format(top))
    boundary_equal = []
    for m in msgs:
        rd = m.get("receivedDateTime", "")
        eq = rd == watermark_time
        if eq:
            boundary_equal.append(m.get("id"))
        print(json.dumps({
            "id": m.get("id"),
            "receivedDateTime": rd,
            "subject": (m.get("subject") or "")[:120],
            "hasAttachments": m.get("hasAttachments"),
            "internetMessageId": m.get("internetMessageId"),
            "from": (m.get("from", {}) or {}).get("emailAddress", {}).get("address"),
            "boundary_equal_to_watermark": eq,
        }, indent=2))

    print("\n=== boundary-equal analysis ===")
    print(json.dumps({
        "watermark": watermark_time,
        "messages_at_boundary": len(boundary_equal),
        "boundary_message_ids": boundary_equal,
        "diagnosis": (
            "Graph is returning boundary-equal messages despite strict gt — "
            "most likely cause: Graph stores receivedDateTime at sub-second "
            "precision and serializes it back to second precision in JSON. "
            "Server-side gt comparison passes (12:06:58.123 > 12:06:58), but "
            "our string max() then ties at the second-precision string. The "
            "fix is a tie-breaker that tracks message IDs already processed "
            "at the watermark second."
        ) if boundary_equal else
        "No boundary-equal messages — stall has another cause; capture next stalled run for review."
    }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    return asyncio.run(main_async(args.top))


if __name__ == "__main__":
    raise SystemExit(main())
