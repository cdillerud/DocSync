"""
BC Post Claim Service — atomic claim primitive for BC write operations.

Problem it solves
-----------------
The AP auto-post, SO auto-create, and manual Post-to-BC paths used to
update a document's ``bc_posting_status`` with ``update_one`` and then
call Business Central. Two concurrent callers (background poller +
manual retry, two worker pods, double-click on UI) could both:
  1. read the document, see an eligible status,
  2. flip ``bc_posting_status`` to an in-flight value,
  3. call ``create_purchase_invoice`` / ``create_sales_order``,
producing **duplicate BC records** — a real-money financial defect.

Solution
--------
A single atomic ``find_one_and_update`` that:
  * rejects documents in a terminal success state (posted / created);
  * rejects documents that are actively claimed by another worker —
    unless their claim has exceeded the TTL (self-healing for crashed
    workers / pod evictions);
  * on success, writes the new status, ``bc_posting_claimed_by``,
    ``bc_posting_claimed_at`` in one operation.

All call sites MUST go through ``claim_for_bc_post`` before any BC
write. After the BC call completes (or fails), call ``release_claim``
to move the document to its terminal state and clear the claim fields.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

logger = logging.getLogger(__name__)


# -- State taxonomy -----------------------------------------------------------
# A document in any of these states is the terminal outcome of a previous
# successful BC write — NEVER allow a new claim, regardless of TTL. Re-posting
# would create a duplicate BC record.
TERMINAL_SUCCESS_STATES = ("posted", "created", "auto_posted")

# Transient "someone is working on it" states. A claim in one of these is
# respected unless it has gone stale (claimed_at older than TTL), in which
# case the original worker is presumed dead and the claim is reclaimable.
IN_FLIGHT_STATES = ("auto_posting", "posting", "auto_creating")

# How long a claim can sit in an IN_FLIGHT state before another worker may
# take it over. Configurable for environments with very slow BC responses.
CLAIM_TTL_SECONDS = int(os.environ.get("BC_POST_CLAIM_TTL_SECONDS", "300"))


def _utc_iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat()


def default_worker_id(prefix: str = "worker") -> str:
    """Stable-per-process identifier used when the caller doesn't provide one."""
    return f"{prefix}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class ClaimRejectionReason:
    NOT_FOUND = "not_found"
    ALREADY_TERMINAL = "already_terminal"
    ACTIVE_CLAIM = "active_claim"


class ClaimResult:
    """Outcome of an atomic claim attempt."""

    __slots__ = ("claimed", "document", "reason", "existing_status", "existing_holder")

    def __init__(
        self,
        claimed: bool,
        document: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        existing_status: Optional[str] = None,
        existing_holder: Optional[str] = None,
    ):
        self.claimed = claimed
        self.document = document
        self.reason = reason
        self.existing_status = existing_status
        self.existing_holder = existing_holder

    def to_log_fields(self) -> Dict[str, Any]:
        return {
            "claimed": self.claimed,
            "reason": self.reason,
            "existing_status": self.existing_status,
            "existing_holder": self.existing_holder,
        }


async def claim_for_bc_post(
    db,
    doc_id: str,
    target_state: str,
    worker_id: Optional[str] = None,
    extra_set: Optional[Dict[str, Any]] = None,
    ttl_seconds: Optional[int] = None,
) -> ClaimResult:
    """Atomically claim a document for a BC write.

    Parameters
    ----------
    db
        Motor database reference.
    doc_id
        ``hub_documents.id`` of the target document.
    target_state
        The in-flight state to move the doc into — one of
        ``IN_FLIGHT_STATES``. Typical values:
          * ``"auto_posting"`` — AP auto-post path
          * ``"posting"``      — manual Post-to-BC path
          * ``"auto_creating"`` — SO auto-create path
    worker_id
        Identifier of the caller. Persisted on the document so you can
        trace who holds a stale claim. Auto-generated if omitted.
    extra_set
        Additional fields to set atomically alongside the claim — e.g.
        ``{"auto_post_attempted": True}``. Merged into the ``$set``.
    ttl_seconds
        Override the default claim TTL. Used by tests.

    Returns
    -------
    ClaimResult
        ``claimed=True`` with the refreshed document on success.
        ``claimed=False`` with ``reason`` set otherwise. The caller MUST
        abort the BC write when ``claimed=False``.
    """
    if target_state not in IN_FLIGHT_STATES:
        raise ValueError(
            f"target_state must be one of {IN_FLIGHT_STATES}, got {target_state!r}"
        )

    ttl = ttl_seconds if ttl_seconds is not None else CLAIM_TTL_SECONDS
    now = datetime.now(timezone.utc)
    ttl_cutoff_iso = _utc_iso(now - timedelta(seconds=ttl))
    wid = worker_id or default_worker_id()

    # Atomic filter:
    #   1. Doc must exist (id match).
    #   2. bc_posting_status NOT in TERMINAL_SUCCESS_STATES (never re-post).
    #   3. Either bc_posting_status NOT in IN_FLIGHT_STATES (fresh claim),
    #      OR it IS in-flight but the previous claim has expired (stale).
    filter_ = {
        "id": doc_id,
        "bc_posting_status": {"$nin": list(TERMINAL_SUCCESS_STATES)},
        "$or": [
            {"bc_posting_status": {"$nin": list(IN_FLIGHT_STATES)}},
            {
                "bc_posting_status": {"$in": list(IN_FLIGHT_STATES)},
                "bc_posting_claimed_at": {"$lt": ttl_cutoff_iso},
            },
            # Legacy rows that don't have bc_posting_claimed_at at all are
            # treated as stale (can't be held by a live worker if the field
            # doesn't exist).
            {
                "bc_posting_status": {"$in": list(IN_FLIGHT_STATES)},
                "bc_posting_claimed_at": {"$exists": False},
            },
        ],
    }

    update = {
        "$set": {
            "bc_posting_status": target_state,
            "bc_posting_claimed_at": _utc_iso(now),
            "bc_posting_claimed_by": wid,
            "updated_utc": _utc_iso(now),
            **(extra_set or {}),
        }
    }

    claimed_doc = await db.hub_documents.find_one_and_update(
        filter_, update, return_document=ReturnDocument.AFTER
    )

    if claimed_doc is not None:
        # Strip Mongo _id before returning (consumers serialize this).
        claimed_doc.pop("_id", None)
        logger.info(
            "[BCPostClaim] Claim ACQUIRED doc=%s target=%s worker=%s",
            doc_id, target_state, wid,
        )
        return ClaimResult(claimed=True, document=claimed_doc)

    # Claim failed — classify the reason by a single diagnostic read.
    existing = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "bc_posting_status": 1, "bc_posting_claimed_by": 1,
         "bc_posting_claimed_at": 1},
    )
    if not existing:
        logger.warning(
            "[BCPostClaim] Claim REJECTED doc=%s reason=%s worker=%s",
            doc_id, ClaimRejectionReason.NOT_FOUND, wid,
        )
        return ClaimResult(claimed=False, reason=ClaimRejectionReason.NOT_FOUND)

    status = existing.get("bc_posting_status")
    holder = existing.get("bc_posting_claimed_by")
    if status in TERMINAL_SUCCESS_STATES:
        logger.info(
            "[BCPostClaim] Claim REJECTED doc=%s reason=%s status=%s worker=%s",
            doc_id, ClaimRejectionReason.ALREADY_TERMINAL, status, wid,
        )
        return ClaimResult(
            claimed=False,
            reason=ClaimRejectionReason.ALREADY_TERMINAL,
            existing_status=status,
            existing_holder=holder,
        )

    logger.info(
        "[BCPostClaim] Claim REJECTED doc=%s reason=%s status=%s holder=%s worker=%s",
        doc_id, ClaimRejectionReason.ACTIVE_CLAIM, status, holder, wid,
    )
    return ClaimResult(
        claimed=False,
        reason=ClaimRejectionReason.ACTIVE_CLAIM,
        existing_status=status,
        existing_holder=holder,
    )


async def release_claim(
    db,
    doc_id: str,
    final_state: str,
    extra_set: Optional[Dict[str, Any]] = None,
    attempt: Optional[Dict[str, Any]] = None,
) -> None:
    """Finalize a claimed document after the BC call completes.

    Clears ``bc_posting_claimed_*`` fields and writes the terminal state
    (``posted`` / ``created`` / ``auto_post_failed`` / ...). Idempotent
    — safe to call in both success and failure paths.

    If ``attempt`` is provided (a dict built via
    ``services.bc_posting_attempts.build_attempt``), it is atomically
    ``$push``ed onto ``hub_documents.bc_posting_attempts`` alongside the
    terminal-state write — so the final outcome and its audit entry land
    in one operation and can never drift apart.
    """
    update: Dict[str, Any] = {
        "$set": {
            "bc_posting_status": final_state,
            "bc_posting_claimed_at": None,
            "bc_posting_claimed_by": None,
            "updated_utc": _utc_iso(),
            **(extra_set or {}),
        }
    }
    if attempt is not None:
        update["$push"] = {"bc_posting_attempts": attempt}
    await db.hub_documents.update_one({"id": doc_id}, update)
    logger.info(
        "[BCPostClaim] Claim RELEASED doc=%s final_state=%s attempt=%s",
        doc_id, final_state, bool(attempt),
    )
