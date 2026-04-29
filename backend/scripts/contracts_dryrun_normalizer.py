"""Phase 3.2 — DocuSign payload dry-run helper.

Runs the agreement_normalizer against a captured DocuSign Connect SIM payload
WITHOUT touching MongoDB. Use this BEFORE firing real envelopes to catch
field-shape mismatches early.

Usage:

    # Save a DocuSign Connect message from your Connect log to a file:
    #   /tmp/connect_event.json
    docker compose exec backend \\
        python -m scripts.contracts_dryrun_normalizer /tmp/connect_event.json

    # Or pipe from stdin:
    cat /tmp/connect_event.json | \\
        docker compose exec -T backend python -m scripts.contracts_dryrun_normalizer -

The script prints:
    * Resolved envelope id + status
    * Sender + party rows (with normalized_org for matching diagnostics)
    * Term rows (custom fields + form data)
    * Pricing rows (line bucket parsing — confirms your tab convention works)
    * Document rows
    * Any warnings emitted by the normalizer

Exit codes:
    0 on success (normalizer ran cleanly, even if there were warnings)
    2 if the payload is missing the envelope id (irrecoverable)
    3 if the input file cannot be read / is not JSON
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.contracts.agreement_normalizer import normalize_envelope  # noqa: E402


def _load_payload(arg: str) -> Dict[str, Any]:
    if arg == "-":
        raw = sys.stdin.read()
    else:
        with open(arg, "r", encoding="utf-8") as fp:
            raw = fp.read()
    if not raw.strip():
        raise ValueError("empty payload")
    return json.loads(raw)


def _print_section(title: str, rows: list, *, fields: list) -> None:
    print(f"\n=== {title} ({len(rows)}) ===")
    if not rows:
        print("  (none)")
        return
    for i, r in enumerate(rows, 1):
        d = r.model_dump(mode="json") if hasattr(r, "model_dump") else r
        bits = [f"{k}={d.get(k)}" for k in fields if d.get(k) is not None]
        print(f"  {i:>2}. " + " · ".join(bits))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: contracts_dryrun_normalizer.py <path-to-payload.json|->",
              file=sys.stderr)
        return 1
    try:
        payload = _load_payload(sys.argv[1])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read payload — {exc}", file=sys.stderr)
        return 3

    print("DocuSign normalizer dry-run")
    print(f"input event: {payload.get('event', '?')}")
    if isinstance(payload.get("data"), dict):
        env_id = payload["data"].get("envelopeId")
        print(f"input envelopeId: {env_id}")

    try:
        n = normalize_envelope(payload, event_id="dryrun-cli")
    except ValueError as exc:
        print(f"\nFATAL: normalizer rejected payload: {exc}", file=sys.stderr)
        print("\nMost likely cause: the envelopeSummary lacks `envelopeId`.",
              file=sys.stderr)
        return 2

    a = n.agreement
    print(f"\nResolved agreement: provider_envelope_id={a.provider_envelope_id} "
          f"status={a.status} title={(a.title or '')[:80]!r}")
    print(f"  sender: {a.sender_name!r} <{a.sender_email}>")
    print(f"  sent_at={a.sent_at}  completed_at={a.completed_at}  "
          f"expires_at={a.expires_at}")
    print(f"  party_count={a.party_count}  document_count={a.document_count}")

    _print_section(
        "Parties", n.parties,
        fields=["role", "name", "email", "organization",
                "normalized_org", "signing_status", "routing_order"],
    )
    _print_section(
        "Terms", n.terms,
        fields=["term_key", "term_value", "source", "confidence"],
    )
    _print_section(
        "Pricing", n.pricing,
        fields=["line_no", "item_label", "quantity", "uom",
                "unit_price", "line_total", "currency", "confidence"],
    )
    _print_section(
        "Documents", n.documents,
        fields=["provider_document_id", "name", "mime_type",
                "page_count", "size_bytes"],
    )

    print(f"\n=== Warnings ({len(n.warnings)}) ===")
    for w in n.warnings:
        print(f"  - code={w.get('code')} details={w.get('details')}")

    print("\nDry-run complete. No DB writes were made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
