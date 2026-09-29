"""
scripts/hub_classification_quality_report.py
=============================================
P0 cutover proof, quality layer: for every document the parity report
already found in BOTH Square9 and Hub ("matched"), check whether Hub's
OWN classification of that document is actually correct -- not just
whether Hub has a copy of it.

Why this exists: square9_hub_ap_parity_report.py answers "does Hub have
what Square9 has" (coverage / recall). It says nothing about whether
Hub's routing/doc_type decision on a matched document is right. A
document can be "matched" (a parity win) while Hub still filed it as
doc_type=OTHER / mailbox_category != AP -- exactly the gap this report
found live on its first run (see readme in cutover proof docs). Coverage
alone cannot tell you Hub is BETTER than Square9, only that it caught up.

Method: Square9's own human-organized folder structure is itself a
signal. A document Square9 staff filed under a known AP-lane folder root
(Dropship International, Dropship Not International, Warehouse
International, Warehouse Not International, Freight, S&H Invoices,
Misc Invoices, Vendor Credit Memos) was, by definition, treated as a real
AP invoice by the people who run AP today. If Hub's own doc_type for
that SAME matched document is not one of the real invoice types
(routers/queue_constants.AP_TYPES -- the same canonical list the rest of
the app already uses, not a new one invented here), that is a genuine
disagreement worth surfacing, regardless of whether the parity report
counted the document as "matched".

Read-only: reads the parity CSV + hub_documents for extra fields, writes
one JSON report. No writes anywhere.
"""

import csv
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.queue_constants import AP_TYPES  # noqa: E402

MATCHED_BUCKETS = {
    "exact_match", "strong_evidence_match", "likely_match",
    "possible_match", "llm_assisted_match",
}

# Known AP-lane folder roots in Square9's own filing structure. A document
# sitting under one of these was treated as a real vendor invoice by AP
# staff today -- this is Square9's own ground truth, not a guess.
KNOWN_AP_FOLDER_ROOTS = (
    "dropship international",
    "dropship not international",
    "warehouse international",
    "warehouse not international",
    "freight",
    "s&h invoices",
    "misc invoices",
    "vendor credit memos",
)

# doc_type values that mean "Hub gave up / never got a confident answer".
UNRESOLVED_HUB_TYPES = {"other", "unknown", "unknown_document", ""}


def square9_says_ap_invoice(parent_path: str) -> bool:
    p = (parent_path or "").lower()
    return any(root in p for root in KNOWN_AP_FOLDER_ROOTS)


def hub_says_ap_invoice(doc_type: str) -> bool:
    return (doc_type or "") in AP_TYPES


def main() -> int:
    parity_csv = "prod_reports/square9_hub_ap_parity.csv"
    out_json = "prod_reports/hub_classification_quality.json"

    with open(parity_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    matched = [r for r in rows if r["match_bucket"] in MATCHED_BUCKETS]

    agreements = 0
    silent_misses: List[Dict[str, Any]] = []
    unresolved_but_ap_lane = 0

    for r in matched:
        sq9_ap = square9_says_ap_invoice(r["square9_parent_path"])
        # doc_type and document_type are known to disagree on some records
        # (the AI classifier writes a correct type to document_type/
        # suggested_job_type but a sibling doc_type field is stale) --
        # already defensively handled in ~20 other files in this codebase
        # via this same fallback chain. Reading doc_type alone here produced
        # a false "classification miss" against a document that was
        # actually classified correctly.
        hub_type = (
            r.get("hub_doc_type")
            or r.get("hub_suggested_job_type")
            or ""
        )
        hub_ap = hub_says_ap_invoice(hub_type)

        if not sq9_ap:
            # Square9 didn't file this under a known AP lane either --
            # not a disagreement we can judge from folder structure alone.
            continue

        if hub_ap:
            agreements += 1
            continue

        # Square9 says AP invoice, Hub's doc_type disagrees.
        is_unresolved = hub_type.lower() in UNRESOLVED_HUB_TYPES
        if is_unresolved:
            unresolved_but_ap_lane += 1
        silent_misses.append({
            "hub_doc_id": r.get("hub_doc_id"),
            "hub_file_name": r.get("hub_file_name"),
            "hub_doc_type": hub_type,
            "hub_suggested_job_type": r.get("hub_suggested_job_type"),
            "hub_classification_method": r.get("hub_classification_method"),
            "hub_vendor_canonical": r.get("hub_vendor_canonical"),
            "hub_routing_status": r.get("hub_routing_status"),
            "square9_name": r.get("square9_name"),
            "square9_parent_path": r.get("square9_parent_path"),
            "match_bucket": r.get("match_bucket"),
            "match_score": r.get("match_score"),
            "severity": "unresolved_classification" if is_unresolved else "wrong_classification",
        })

    total_ap_lane_matched = agreements + len(silent_misses)
    agreement_rate = (agreements / total_ap_lane_matched) if total_ap_lane_matched else None

    result = {
        "total_matched_docs": len(matched),
        "total_square9_ap_lane_matched": total_ap_lane_matched,
        "agreements": agreements,
        "disagreements": len(silent_misses),
        "disagreements_unresolved_classification": unresolved_but_ap_lane,
        "disagreements_wrong_classification": len(silent_misses) - unresolved_but_ap_lane,
        "agreement_rate_pct": (
            round(agreement_rate * 100, 2) if agreement_rate is not None else None
        ),
        "disagreement_examples": silent_misses[:25],
    }

    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    print(
        f"[quality] {total_ap_lane_matched} Square9-confirmed-AP-lane docs matched in Hub; "
        f"agree={agreements} disagree={len(silent_misses)} "
        f"(unresolved={unresolved_but_ap_lane}, "
        f"wrong={len(silent_misses) - unresolved_but_ap_lane}); "
        f"agreement_rate={result['agreement_rate_pct']}%",
        file=sys.stderr,
    )
    print(json.dumps(result, indent=2, default=str))

    # Signal code: 0 = clean, 2 = disagreements found (workflow signal, not
    # a hard failure -- mirrors the repo's own rc=0/1/2 convention).
    return 2 if silent_misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
