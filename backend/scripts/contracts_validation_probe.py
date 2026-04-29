"""Phase 3.2 — Post-event Contract Intelligence inspector.

Read-only diagnostic. Dumps the persisted state of one or more agreements
matching a filter. Use AFTER firing a DocuSign event through the webhook to
verify the pipeline did the expected things.

Usage examples:

    # Inspect by envelope id (most precise):
    docker compose exec backend python -m scripts.contracts_validation_probe \\
        --envelope-id env-1234

    # Inspect the most recently received event (and the agreement it produced):
    docker compose exec backend python -m scripts.contracts_validation_probe \\
        --latest

    # Show the last N events regardless of envelope:
    docker compose exec backend python -m scripts.contracts_validation_probe \\
        --recent-events 10

This script NEVER writes to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from database import db  # noqa: E402
from models.contracts import CONTRACTS_COLLECTIONS  # noqa: E402


def _short(v: Any, n: int = 80) -> str:
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_rows(title: str, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    print(f"\n=== {title} ({len(rows)}) ===")
    if not rows:
        print("  (none)")
        return
    for i, r in enumerate(rows, 1):
        bits = [f"{k}={_short(r.get(k))}" for k in fields if r.get(k) is not None]
        print(f"  {i:>2}. " + " · ".join(bits))


async def _events_for_envelope(envelope_id: str) -> List[Dict[str, Any]]:
    coll = db[CONTRACTS_COLLECTIONS["agreement_events"]]
    return await coll.find(
        {"provider_envelope_id": envelope_id}, {"_id": 0},
    ).sort("received_at", -1).to_list(length=50)


async def _agreement_for_envelope(envelope_id: str) -> Optional[Dict[str, Any]]:
    coll = db[CONTRACTS_COLLECTIONS["agreements"]]
    return await coll.find_one(
        {"provider_envelope_id": envelope_id}, {"_id": 0},
    )


async def _children(coll_name: str, agreement_id: str) -> List[Dict[str, Any]]:
    return await db[CONTRACTS_COLLECTIONS[coll_name]].find(
        {"agreement_id": agreement_id}, {"_id": 0},
    ).to_list(length=None)


async def _audit(agreement_id: str) -> List[Dict[str, Any]]:
    return await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
        {"agreement_id": agreement_id}, {"_id": 0},
    ).sort("at", -1).to_list(length=200)


async def _inspect_envelope(envelope_id: str) -> int:
    print(f"# Inspecting envelope: {envelope_id}")

    events = await _events_for_envelope(envelope_id)
    _print_rows("Events", events, [
        "id", "provider_event_id", "event_type", "received_at", "transport",
        "hmac_valid", "processed", "processed_at", "error",
    ])
    if not events:
        print("\n(!) No events found for this envelope id. Possible causes:")
        print("    1. HMAC validation failed (returns 401, never persisted).")
        print("    2. DocuSign Connect not configured to point at this URL.")
        print("    3. Different envelope id (check provider_envelope_id field).")
        return 0

    agreement = await _agreement_for_envelope(envelope_id)
    if not agreement:
        print("\n(!) Events received but no agreement persisted. The")
        print("    background processor may have failed. Inspect events above")
        print("    for `error` field; check backend logs for exceptions.")
        return 0

    print("\n=== Agreement ===")
    for k in ("id", "status", "title", "email_subject", "sender_name",
              "sender_email", "sent_at", "completed_at", "expires_at",
              "party_count", "document_count", "has_unmatched_exceptions",
              "last_event_id", "last_normalized_at"):
        print(f"  {k}: {agreement.get(k)}")

    aid = agreement["id"]
    parties = await _children("agreement_parties", aid)
    _print_rows("Parties", parties, [
        "role", "name", "email", "organization", "normalized_org",
        "signing_status", "routing_order", "provider_recipient_id",
    ])
    terms = await _children("agreement_terms", aid)
    _print_rows("Terms", terms, [
        "term_key", "term_value", "source", "confidence",
    ])
    pricing = await _children("agreement_pricing", aid)
    _print_rows("Pricing", pricing, [
        "line_no", "item_label", "quantity", "uom",
        "unit_price", "line_total", "currency", "confidence",
    ])
    documents = await _children("agreement_documents", aid)
    _print_rows("Documents", documents, [
        "provider_document_id", "name", "mime_type", "page_count", "size_bytes",
    ])
    links = await _children("agreement_bc_links", aid)
    _print_rows("BC Links", links, [
        "link_type", "bc_no", "bc_name_snapshot",
        "match_method", "confidence", "status", "linked_by",
    ])
    exceptions = await _children("agreement_exceptions", aid)
    _print_rows("Exceptions", exceptions, [
        "code", "severity", "status", "details", "opened_at",
    ])
    audit = await _audit(aid)
    _print_rows("Audit (newest first)", audit, [
        "at", "action", "actor", "link_id", "exception_id", "notes",
    ])

    return 0


async def _inspect_latest() -> int:
    coll = db[CONTRACTS_COLLECTIONS["agreement_events"]]
    latest = await coll.find_one({}, {"_id": 0}, sort=[("received_at", -1)])
    if not latest:
        print("(no events found)")
        return 0
    env_id = latest.get("provider_envelope_id") or "(none)"
    print(f"# Latest event: id={latest.get('id')} type={latest.get('event_type')} "
          f"received_at={latest.get('received_at')} "
          f"envelope={env_id} processed={latest.get('processed')}")
    if env_id == "(none)":
        print("(event has no envelope id — payload shape may not be supported)")
        return 0
    return await _inspect_envelope(env_id)


async def _inspect_recent_events(limit: int) -> int:
    coll = db[CONTRACTS_COLLECTIONS["agreement_events"]]
    rows = await coll.find({}, {"_id": 0}).sort("received_at", -1).limit(limit).to_list(length=limit)
    _print_rows(f"Recent events (limit={limit})", rows, [
        "received_at", "event_type", "provider_event_id",
        "provider_envelope_id", "hmac_valid", "processed", "error",
    ])
    return 0


async def main_async(args: argparse.Namespace) -> int:
    if args.envelope_id:
        return await _inspect_envelope(args.envelope_id)
    if args.latest:
        return await _inspect_latest()
    if args.recent_events:
        return await _inspect_recent_events(args.recent_events)
    print("nothing to do; pass --envelope-id, --latest, or --recent-events N",
          file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope-id", help="DocuSign envelope id to inspect")
    parser.add_argument("--latest", action="store_true",
                        help="Inspect the most recently received event + its agreement")
    parser.add_argument("--recent-events", type=int, metavar="N",
                        help="Show the last N events regardless of envelope")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
