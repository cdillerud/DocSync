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


async def apply_manual_routing_correction(
    db, doc_id: str, doc: dict, new_mailbox_category: str,
    corrected_by: str, now: str,
) -> dict:
    """Applies a human-initiated routing correction on a single
    document: updates hub_documents.mailbox_category, and
    unconditionally writes/overwrites a sender routing override rule
    so every future document from the same sender routes correctly
    from the start - not just this one document, retroactively.

    A direct human correction is the highest-trust signal available in
    this system - deliberately no confidence score, no cohort-size
    threshold, no idempotency skip. If a rule already exists for this
    sender (e.g. from an earlier automated inference), the fresh human
    correction unconditionally overwrites it, since a person looking
    at this specific document right now supersedes an earlier guess.

    No-ops cleanly (routing_changed=False) if new_mailbox_category
    already matches the document's current value - nothing to correct,
    and no sender rule write is attempted in that case either.

    Raises nothing - a routing-override write failure is caught,
    logged, and reported in the return value rather than propagated,
    so a bulk-classify call correcting several documents can't have
    the whole batch fail because of one sender-rule write hiccup.
    """
    result = {
        "routing_changed": False,
        "prior_mailbox_category": doc.get("mailbox_category"),
        "sender_rule_written": False,
        "sender_email": None,
        "error": None,
    }

    prior = doc.get("mailbox_category")
    if prior == new_mailbox_category:
        return result

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "mailbox_category": new_mailbox_category,
            "routing_override": {
                "original_mailbox_category": prior,
                "corrected_mailbox_category": new_mailbox_category,
                "corrected_at": now,
                "corrected_by": corrected_by,
            },
            "updated_utc": now,
        }},
    )
    result["routing_changed"] = True

    sender_key = normalize_sender_email(doc.get("email_sender"))
    if not sender_key:
        return result
    result["sender_email"] = sender_key

    try:
        await db[COLLECTION_NAME].update_one(
            {"sender_email": sender_key},
            {"$set": {
                "sender_email": sender_key,
                "target_mailbox_category": new_mailbox_category,
                "source": "manual_correction",
                "source_doc_id": doc_id,
                "created_at": now,
                "corrected_by": corrected_by,
            }},
            upsert=True,
        )
        result["sender_rule_written"] = True
    except Exception as e:
        logger.warning(
            "[sender_routing_overrides] manual correction rule write "
            "failed for doc=%s sender=%s: %s", doc_id, sender_key, e,
        )
        result["error"] = str(e)

    return result
