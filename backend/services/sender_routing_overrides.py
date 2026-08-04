"""
sender_routing_overrides.py
============================
Sender-scoped routing overrides for dynamic mailbox intake.

A sender override is intentionally broader than a document correction:
it applies regardless of which monitored mailbox receives the next
message. Because of that blast radius, changing one document's lane
must never create or replace a sender rule implicitly.

Collection shape (hub_sender_routing_overrides):
    {
        "sender_email": "mkotlowski@valleydist.com",
        "target_mailbox_category": "AP",
        "source": "manual_correction",
        "source_doc_id": "<document id>",
        "created_at": "<UTC ISO>",
    }

Lookup is fail-safe. Any error or a rule targeting a paused Sales lane
returns None so live intake falls back to the mailbox's configured lane.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hub_sender_routing_overrides"


def normalize_sender_email(raw: Optional[str]) -> Optional[str]:
    """Lowercase and strip a sender address for consistent matching."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return key or None


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _sales_routing_enabled() -> bool:
    """Return whether routing new intake into the Sales lane is allowed."""
    return _env_flag_enabled("SALES_EMAIL_POLLING_ENABLED")


async def get_sender_routing_override(
    db,
    sender_email: Optional[str],
) -> Optional[str]:
    """Return an active sender override category, otherwise None.

    Rules targeting Sales are ignored while Sales polling is paused. This
    prevents stale database configuration from silently routing Warehouse
    or AP intake into a paused Sales workflow.
    """
    key = normalize_sender_email(sender_email)
    if not key:
        return None

    try:
        rule = await db[COLLECTION_NAME].find_one(
            {"sender_email": key},
            {"_id": 0, "target_mailbox_category": 1},
        )
        if not rule:
            return None

        category = rule.get("target_mailbox_category")
        normalized_category = str(category).strip() if category else ""
        if not normalized_category:
            return None

        if (
            normalized_category.lower() == "sales"
            and not _sales_routing_enabled()
        ):
            logger.warning(
                "[sender_routing_overrides] ignored paused Sales rule "
                "for sender=%s",
                key,
            )
            return None

        return normalized_category
    except Exception as e:
        logger.warning(
            "[sender_routing_overrides] lookup failed for %r, "
            "proceeding without override: %s",
            sender_email,
            e,
        )
        return None


async def apply_manual_routing_correction(
    db,
    doc_id: str,
    doc: dict,
    new_mailbox_category: str,
    corrected_by: str,
    now: str,
    *,
    learn_sender_rule: bool = False,
) -> dict:
    """Correct one document's lane, with optional explicit sender learning.

    The safe default is document-only. A caller must explicitly pass
    ``learn_sender_rule=True`` to create or replace a sender-wide rule.
    Sales sender learning is blocked while Sales polling is paused.
    """
    result = {
        "routing_changed": False,
        "prior_mailbox_category": doc.get("mailbox_category"),
        "sender_rule_requested": bool(learn_sender_rule),
        "sender_rule_written": False,
        "sender_rule_blocked_reason": None,
        "sender_email": None,
        "error": None,
    }

    prior = doc.get("mailbox_category")
    if prior == new_mailbox_category:
        return result

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "mailbox_category": new_mailbox_category,
                "routing_override": {
                    "scope": "document",
                    "original_mailbox_category": prior,
                    "corrected_mailbox_category": new_mailbox_category,
                    "corrected_at": now,
                    "corrected_by": corrected_by,
                    "sender_learning_requested": bool(learn_sender_rule),
                },
                "updated_utc": now,
            }
        },
    )
    result["routing_changed"] = True

    sender_key = normalize_sender_email(doc.get("email_sender"))
    result["sender_email"] = sender_key

    if not learn_sender_rule:
        return result

    if not sender_key:
        result["sender_rule_blocked_reason"] = "sender_email_missing"
        return result

    if (
        str(new_mailbox_category).strip().lower() == "sales"
        and not _sales_routing_enabled()
    ):
        result["sender_rule_blocked_reason"] = "sales_routing_paused"
        logger.warning(
            "[sender_routing_overrides] blocked Sales sender rule "
            "while Sales polling is paused: doc=%s sender=%s",
            doc_id,
            sender_key,
        )
        return result

    try:
        await db[COLLECTION_NAME].update_one(
            {"sender_email": sender_key},
            {
                "$set": {
                    "sender_email": sender_key,
                    "target_mailbox_category": new_mailbox_category,
                    "source": "manual_correction",
                    "source_doc_id": doc_id,
                    "created_at": now,
                    "corrected_by": corrected_by,
                }
            },
            upsert=True,
        )
        result["sender_rule_written"] = True
    except Exception as e:
        logger.warning(
            "[sender_routing_overrides] manual correction rule write "
            "failed for doc=%s sender=%s: %s",
            doc_id,
            sender_key,
            e,
        )
        result["error"] = str(e)

    return result
