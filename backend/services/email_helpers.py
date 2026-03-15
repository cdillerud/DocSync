"""
GPI Document Hub - Email Helpers

Email watcher configuration and mailbox subscription management.
Extracted from server.py during Architecture Hardening pass.

Dependencies:
  - deps: get_db(), config vars
  - services.graph_access: get_graph_token()
"""

import logging
from datetime import datetime, timezone, timedelta

import httpx

import deps
from services.graph_access import get_graph_token

logger = logging.getLogger(__name__)


async def get_email_watcher_config() -> dict:
    """Load email watcher configuration from database."""
    db = deps.get_db()
    config = await db.hub_config.find_one({"_key": "email_watcher"}, {"_id": 0})
    if not config:
        return {
            "mailbox_address": "",
            "watch_folder": "Inbox",
            "needs_review_folder": "Needs Review",
            "processed_folder": "Processed",
            "enabled": False,
            "interval_minutes": 5,
            "webhook_subscription_id": None,
            "last_poll_utc": None,
        }
    if "interval_minutes" not in config:
        config["interval_minutes"] = 5
    return config


async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """Create a Microsoft Graph subscription for email notifications."""
    if deps.DEMO_MODE or not deps.GRAPH_CLIENT_ID:
        return {"status": "demo", "message": "Running in demo mode"}

    try:
        token = await get_graph_token()

        subscription_payload = {
            "changeType": "created",
            "notificationUrl": webhook_url,
            "resource": f"users/{mailbox_address}/mailFolders/Inbox/messages",
            "expirationDateTime": (
                datetime.now(timezone.utc).replace(hour=23, minute=59) + timedelta(days=2)
            ).isoformat() + "Z",
            "clientState": "gpi-document-hub-secret",
        }

        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=subscription_payload,
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "status": "ok",
                    "subscription_id": data.get("id"),
                    "expiration": data.get("expirationDateTime"),
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create subscription (HTTP {resp.status_code}): {resp.text[:500]}",
                }

    except Exception as e:
        return {"status": "error", "message": str(e)}
