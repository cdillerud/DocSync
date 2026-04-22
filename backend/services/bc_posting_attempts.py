"""
BC Posting Attempts — append-only history for every Business Central write.

Problem this solves
-------------------
Prior to Lane A A1 (2026-04-22), every BC write path recorded failures by
overwriting ``hub_documents.bc_posting_error``. A doc that failed three
times, succeeded on the fourth try, and then failed on a later retry would
report only the most recent string — the first three attempts, the
intermediate success, and the retry pattern were all gone.

This module introduces an **append-only** ``bc_posting_attempts[]`` array on
``hub_documents`` so every attempt (manual post, auto-post, retry, partial)
is preserved with timestamp, actor, status, error, correlation, and
response snippet. It is the financial-integrity audit surface for BC
writes; accounting can reconstruct exactly what happened to any doc.

Public API
----------
``build_attempt(...)``
    Pure function. Returns the dict that represents one attempt. Caller
    fills in the fields it knows about.

``attempts_push_fragment(attempt)``
    Returns a Mongo ``$push`` fragment for use inside an existing
    ``update_one`` or ``find_one_and_update`` — lets the caller append
    the attempt atomically alongside their other writes (status,
    bc_document_id, etc.).

``record_standalone_attempt(db, doc_id, attempt)``
    Convenience for paths that aren't already performing a doc write.
    Appends the attempt with a single atomic ``$push``.

``migrate_legacy_bc_posting_error(db)``
    One-time idempotent migration. For any document that has
    ``bc_posting_error`` set but no ``bc_posting_attempts`` array, synthesize
    a single legacy-origin attempt entry so reviewers see continuity.
    Runs on startup. Safe to re-run.

Design notes
------------
* ``bc_posting_error`` is **kept** as a fast-access projection of the most
  recent failing attempt. Dashboard aggregations (``routers/dashboard.py``
  at L1315) still read it. The array is the truth; the string is the summary.
* ``attempt_n`` is monotonic per doc (1-indexed). Assigning it is the caller's
  responsibility — we read the current max, add one, pass through.
* Every attempt carries a ``correlation_id`` that ties retries for the same
  logical post together. The manual post path and the initial auto-post
  use a fresh uuid; the retry wrapper (Lane A A2) re-uses the first
  attempt's correlation_id to chain them.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


# Error message size cap. Beyond this we store the full text in ``error_full``
# and truncate ``error`` so the summary string stays indexable/displayable.
ERROR_SUMMARY_MAX = 500

# BC response body cap; same idea — preserve but keep top-level rows sane.
BC_RESPONSE_SNIPPET_MAX = 2000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(s: Optional[str], limit: int) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def new_correlation_id() -> str:
    """Opaque token that ties retries of the same logical post together."""
    return f"bcp-{uuid.uuid4().hex[:16]}"


def build_attempt(
    *,
    attempt_n: int,
    status: str,                          # "posted" | "failed" | "partial" | "pending_retry"
    actor: str,                           # "user:<email>" | "engine:auto_post" | "engine:retry"
    source: str,                          # "manual_post_to_bc" | "auto_post" | "retry" | "auto_post_service"
    correlation_id: str,
    started_utc: Optional[str] = None,
    finished_utc: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    bc_record_no: Optional[str] = None,
    bc_document_id: Optional[str] = None,
    error: Optional[str] = None,
    retry_reason: Optional[str] = None,   # "429" | "503" | "timeout" | "bc_rejection" | None
    gate_id: Optional[str] = None,
    bc_response_snippet: Optional[str] = None,
    partial_lines: Optional[Dict[str, int]] = None,  # {"added": 0, "total": 2} on partial
) -> Dict[str, Any]:
    """Construct a single posting-attempt entry.

    Only ``attempt_n``, ``status``, ``actor``, ``source`` and ``correlation_id``
    are required. All other fields may be ``None`` and will be stored as such
    — keep them present so the shape is stable across retries/attempts.
    """
    now = _utc_iso()
    return {
        "attempt_n": int(attempt_n),
        "attempt_id": uuid.uuid4().hex,
        "correlation_id": correlation_id,
        "started_utc": started_utc or now,
        "finished_utc": finished_utc or now,
        "elapsed_ms": elapsed_ms,
        "status": status,
        "actor": actor,
        "source": source,
        "bc_record_no": bc_record_no,
        "bc_document_id": bc_document_id,
        "error": _truncate(error, ERROR_SUMMARY_MAX),
        "error_full": error if (error and len(error) > ERROR_SUMMARY_MAX) else None,
        "retry_reason": retry_reason,
        "gate_id": gate_id,
        "bc_response_snippet": _truncate(bc_response_snippet, BC_RESPONSE_SNIPPET_MAX),
        "partial_lines": partial_lines,
    }


def attempts_push_fragment(attempt: Dict[str, Any]) -> Dict[str, Any]:
    """Return a Mongo update fragment that appends ``attempt`` atomically.

    Usage:
        update = {
            "$set": {"bc_posting_status": "posted", ...},
            **attempts_push_fragment(attempt),
        }
        await db.hub_documents.update_one({"id": doc_id}, update)
    """
    return {"$push": {"bc_posting_attempts": attempt}}


async def next_attempt_n(db, doc_id: str) -> int:
    """Return the next 1-indexed attempt number for ``doc_id``."""
    doc = await db.hub_documents.find_one(
        {"id": doc_id}, {"_id": 0, "bc_posting_attempts": 1}
    )
    if not doc:
        return 1
    attempts = doc.get("bc_posting_attempts") or []
    return len(attempts) + 1


async def record_standalone_attempt(
    db,
    doc_id: str,
    attempt: Dict[str, Any],
    *,
    also_set: Optional[Dict[str, Any]] = None,
) -> None:
    """Append ``attempt`` to ``hub_documents.bc_posting_attempts`` atomically.

    For paths that need to record an attempt without also doing a
    ``release_claim`` — e.g., an auto-post that ends up in
    ``pending_retry`` without releasing a claim because no claim was ever
    acquired. ``also_set`` is merged into the ``$set`` so callers can
    update ``bc_posting_error`` (the fast-access summary projection) at
    the same time.
    """
    update: Dict[str, Any] = {
        "$set": {"updated_utc": _utc_iso(), **(also_set or {})},
        "$push": {"bc_posting_attempts": attempt},
    }
    await db.hub_documents.update_one({"id": doc_id}, update)


async def migrate_legacy_bc_posting_error(db) -> Dict[str, int]:
    """One-time migration for documents predating A1.

    For any ``hub_documents`` row that has ``bc_posting_error`` set (non-empty)
    but no ``bc_posting_attempts`` array, synthesize a single legacy-origin
    entry reflecting what we know. Idempotent: rows that already carry the
    array are skipped.

    Returns a dict of counters suitable for logging at startup.
    """
    migrated = 0
    scanned = 0

    cursor = db.hub_documents.find(
        {
            "bc_posting_error": {"$exists": True, "$nin": [None, ""]},
            "bc_posting_attempts": {"$exists": False},
        },
        {
            "_id": 0, "id": 1, "bc_posting_status": 1,
            "bc_posting_error": 1, "bc_document_id": 1,
            "bc_document_number": 1, "posted_to_bc_utc": 1, "updated_utc": 1,
        },
    )
    async for row in cursor:
        scanned += 1
        # Best-effort synthesis — use the most recent timestamp we have.
        finished_at = (
            row.get("posted_to_bc_utc")
            or row.get("updated_utc")
            or _utc_iso()
        )
        attempt = build_attempt(
            attempt_n=1,
            status=row.get("bc_posting_status") or "failed",
            actor="legacy_migration",
            source="legacy_migration",
            correlation_id=f"legacy-{row['id']}",
            started_utc=finished_at,
            finished_utc=finished_at,
            elapsed_ms=None,
            bc_record_no=row.get("bc_document_number"),
            bc_document_id=row.get("bc_document_id"),
            error=row.get("bc_posting_error"),
        )
        await db.hub_documents.update_one(
            {"id": row["id"], "bc_posting_attempts": {"$exists": False}},
            {
                "$set": {
                    "bc_posting_attempts_migrated_utc": _utc_iso(),
                    "updated_utc": _utc_iso(),
                },
                "$push": {"bc_posting_attempts": attempt},
            },
        )
        migrated += 1

    if migrated:
        logger.info(
            "[bc_posting_attempts] legacy migration: scanned=%d migrated=%d",
            scanned, migrated,
        )
    return {"scanned": scanned, "migrated": migrated}
