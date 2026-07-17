"""
sender_routing_overrides.py
============================
The missing "learning" mechanism for mailbox-category routing
decisions - the routing equivalent of what classification_corrections
already does for doc_type classification via build_feedback_context_
for_prompt().

Why this exists (2026-07-17): confirmed live that mailbox_category is
set purely from which monitored mailbox source an email arrived
through (email_polling_service.py's dynamic intake path: resolved_
category = normalize_mailbox_category(default_category), where
default_category is a per-mailbox-source config value, never sender-
specific). Traced 3 real, high-confidence misrouted documents
(MKotlowski@valleydist.com, kbowman@malg.us, rob@rotondowarehouse.com
- all AP-invoice-sending vendors whose mail happens to land in an
Operations-configured mailbox) back to exactly this: there was no
mechanism at all for the system to remember "mail from this sender is
actually AP, route it there" - every future email from the same
sender would be misrouted again, forever, with no way to learn from
the correction bucket_A_high_confidence_routing_fix.py just applied.

This collection and lookup function close that gap. A routing
override is intentionally sender-scoped (not mailbox-scoped) - it
says "regardless of which monitored mailbox this arrives through,
mail from this specific sender belongs in this category" - which
matches the actual real-world pattern (a vendor's AP invoices and
their other correspondence both land in the same operational inbox).

Collection shape (hub_sender_routing_overrides):
    {
        "sender_email": "mkotlowski@valleydist.com",  (always lowercased)
        "target_mailbox_category": "AP",
        "source": "bucket_A_routing_rule_addition_apply",
        "source_cohort_key": {...},   # traceability back to the cohort
        "affected_doc_count_at_creation": 1,
        "created_at": "<UTC ISO>",
    }

Lookup is deliberately fail-safe: any error (DB unavailable, bad data
shape, etc.) is caught and logged, returning None rather than raising
- a routing-override lookup must never be able to break live email
intake. Absence of an override is the overwhelmingly common case and
must resolve to "use the existing, unchanged behavior" every time.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hub_sender_routing_overrides"


def normalize_sender_email(raw: Optional[str]) -> Optional[str]:
    """Lowercases and strips a sender address for consistent matching.
    Returns None for blank/missing input rather than an empty string,
    so callers can cleanly skip the lookup instead of querying for ''."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return key or None


async def get_sender_routing_override(db, sender_email: Optional[str]) -> Optional[str]:
    """Returns the target_mailbox_category for this sender if an
    override rule exists, else None. Never raises - any failure is
    logged and treated as "no override", so a lookup problem can
    never interrupt live email intake."""
    key = normalize_sender_email(sender_email)
    if not key:
        return None
    try:
        rule = await db[COLLECTION_NAME].find_one(
            {"sender_email": key}, {"_id": 0, "target_mailbox_category": 1}
        )
        if not rule:
            return None
        category = rule.get("target_mailbox_category")
        return str(category).strip() or None if category else None
    except Exception as e:
        logger.warning(
            "[sender_routing_overrides] lookup failed for %r, "
            "proceeding without override: %s", sender_email, e,
        )
        return None
