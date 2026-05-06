"""
bucket_A_root_cause_report.py
=============================
READ-ONLY diagnostic. Consumes the resolved triage CSV produced by
`square9_only_triage_resolver.py` and analyzes Bucket A (Hub HAS the
doc but classified outside AP) by enriching each row from the live
`hub_documents` collection (email_sender, email_subject,
classification_method, routing_reason) and grouping into cohorts to
expose root causes.

Read-only. No routing or classifier changes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Root-cause heuristics
# ---------------------------------------------------------------------------

AP_FOLDER_HINT_RE = re.compile(
    r"(?:S&H Invoices|Vendor Credit|Misc Invoices|Warehouse|Dropship|"
    r"Freight|Ball Orders)",
    re.IGNORECASE,
)
NON_AP_DOC_PATTERNS = (
    "Allocation - EM",
    "Allocation-EM",
    "Template",
    "DO NOT PAY",
    "Expected Vendor Credits",
    ".pst",
    "Work Instructions",
)


def _is_non_ap_document(name: str, parent_path: str) -> bool:
    blob = f"{name} {parent_path}"
    lo = blob.lower()
    for p in NON_AP_DOC_PATTERNS:
        if p.lower() in lo:
            return True
    return False


def classify_root_cause(row: Dict[str, str]) -> str:
    """Return one of:
      - high_confidence_AP_invoice_misrouted
      - sales_mailbox_captured_AP_invoice
      - operations_mailbox_captured_AP_invoice
      - classifier_overrode_AP_evidence
      - square9_ap_folder_contains_non_ap_document
      - low_confidence_match_ambiguous
      - uncertain
    """
    try:
        score = float(row.get("best_match_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    cat = (row.get("best_hub_mailbox_category") or "").strip()
    cat_lo = cat.lower()
    doc_type = (row.get("best_hub_doc_type") or "").strip()
    job = (row.get("best_hub_suggested_job_type") or "").strip()
    sq_name = row.get("square9_name") or ""
    sq_parent = row.get("square9_parent_path") or ""

    if _is_non_ap_document(sq_name, sq_parent):
        return "square9_ap_folder_contains_non_ap_document"

    if score < 0.60:
        return "low_confidence_match_ambiguous"

    # High-confidence misrouting: Hub said it IS an AP invoice, but
    # mailbox_category is something else.
    if score >= 0.90 and (
        doc_type.upper() == "AP_INVOICE" or job.lower() == "ap_invoice"
    ) and cat.upper() != "AP":
        return "high_confidence_AP_invoice_misrouted"

    if cat_lo == "sales":
        return "sales_mailbox_captured_AP_invoice"

    if cat_lo in ("operations", "ops"):
        return "operations_mailbox_captured_AP_invoice"

    # Score >= 0.60 but neither sales/ops nor high-confidence AP doc_type
    # → classifier disagreement (e.g. doc_type=SALES_INVOICE in non-sales
    # mailbox, or doc_type=Other).
    if doc_type and doc_type.upper() != "AP_INVOICE":
        return "classifier_overrode_AP_evidence"

    return "uncertain"


# ---------------------------------------------------------------------------
# Mongo enrichment
# ---------------------------------------------------------------------------

ENRICHMENT_FIELDS = (
    "id", "file_name", "email_sender", "email_subject",
    "classification_method", "routing_status", "routing_reason",
    "folder_routing_reason", "mailbox_category", "doc_type",
    "suggested_job_type", "sharepoint_folder_path",
)


def enrich_from_hub(doc_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = [d for d in doc_ids if d]
    if not ids:
        return {}
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    proj = {"_id": 0}
    for f in ENRICHMENT_FIELDS:
        proj[f] = 1
    out: Dict[str, Dict[str, Any]] = {}
    cursor = db.hub_documents.find({"id": {"$in": ids}}, proj)
    for d in cursor:
        out[str(d.get("id") or "")] = d
    return out


# ---------------------------------------------------------------------------
# Cohort grouping
# ---------------------------------------------------------------------------

COHORT_KEYS = (
    "email_sender", "best_hub_mailbox_category", "best_hub_doc_type",
    "best_hub_suggested_job_type", "classification_method",
    "sharepoint_folder_root", "routing_status", "routing_reason",
    "filename_pattern", "square9_parent_root",
)


def _filename_pattern(name: str) -> str:
    """Coarse filename signature: keep alphabetic tokens >=3 chars,
    drop digits/dates/order-numbers. Used to cluster by vendor-naming
    convention."""
    if not name:
        return ""
    base = name.rsplit(".", 1)[0] if "." in name else name
    tokens = re.findall(r"[A-Za-z]{3,}", base)
    return " ".join(t.upper() for t in tokens[:6])


def _root_segment(path: str) -> str:
    if not path:
        return ""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if not parts:
        return ""
    if parts[0].lower() == "temp folder" and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def build_enriched_row(row: Dict[str, str],
                       enrichment: Dict[str, Any]) -> Dict[str, Any]:
    e = enrichment or {}
    cohort_keys = {
        "email_sender": (e.get("email_sender") or "").strip(),
        "email_subject": (e.get("email_subject") or "").strip(),
        "classification_method": (e.get("classification_method") or "").strip(),
        "routing_reason": (
            e.get("folder_routing_reason") or e.get("routing_reason") or ""
        ).strip(),
        "best_hub_mailbox_category": (
            row.get("best_hub_mailbox_category") or ""
        ).strip(),
        "best_hub_doc_type": (row.get("best_hub_doc_type") or "").strip(),
        "best_hub_suggested_job_type": (
            row.get("best_hub_suggested_job_type") or ""
        ).strip(),
        "best_hub_sharepoint_folder_path": (
            row.get("best_hub_sharepoint_folder_path") or ""
        ).strip(),
        "routing_status": (row.get("best_hub_routing_status") or "").strip(),
        "sharepoint_folder_root": _root_segment(
            row.get("best_hub_sharepoint_folder_path") or ""
        ),
        "filename_pattern": _filename_pattern(row.get("square9_name") or ""),
        "square9_parent_root": _root_segment(
            row.get("square9_parent_path") or ""
        ),
    }
    out = dict(row)
    out.update(cohort_keys)
    out["root_cause"] = classify_root_cause(row)
    return out


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "root_cause", "square9_name", "square9_parent_path",
    "square9_parent_root", "filename_pattern", "best_hub_doc_id",
    "best_hub_file_name", "best_hub_mailbox_category", "best_hub_doc_type",
    "best_hub_suggested_job_type", "classification_method",
    "best_hub_sharepoint_folder_path", "sharepoint_folder_root",
    "routing_status", "routing_reason", "email_sender", "email_subject",
    "best_match_score", "best_match_reason",
]


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_resolved_bucket_A(path: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("bucket") or "").strip().upper() == "A":
                out.append(r)
    return out


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(rows: List[Dict[str, str]],
            enrichment: Dict[str, Dict[str, Any]]
            ) -> Dict[str, Any]:
    enriched = [
        build_enriched_row(r, enrichment.get(r.get("best_hub_doc_id") or "", {}))
        for r in rows
    ]

    cohort_counter: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        key = tuple(r.get(k, "") for k in COHORT_KEYS)
        cohort_counter[key].append(r)

    cohorts = []
    for key, members in cohort_counter.items():
        sample = members[0]
        cohorts.append({
            "count": len(members),
            "cohort_key": dict(zip(COHORT_KEYS, key)),
            "root_causes": Counter(m["root_cause"] for m in members).most_common(),
            "example_square9_name": sample.get("square9_name", ""),
            "example_hub_doc_id": sample.get("best_hub_doc_id", ""),
            "example_hub_file_name": sample.get("best_hub_file_name", ""),
            "example_email_sender": sample.get("email_sender", ""),
            "example_email_subject": (sample.get("email_subject") or "")[:120],
            "best_match_score_avg": round(
                sum(float(m.get("best_match_score") or 0) for m in members)
                / len(members),
                3,
            ),
        })
    cohorts.sort(key=lambda c: -c["count"])

    high_conf_misrouted = [
        r for r in enriched
        if r["root_cause"] == "high_confidence_AP_invoice_misrouted"
    ]
    ap_doc_in_non_ap_mailbox = [
        r for r in enriched
        if (r.get("best_hub_doc_type") or "").upper() == "AP_INVOICE"
        and (r.get("best_hub_mailbox_category") or "").upper() != "AP"
    ]
    sales_classified_in_ap_folder = [
        r for r in enriched
        if (r.get("best_hub_doc_type") or "").upper() in {"SALES_INVOICE"}
        or (r.get("best_hub_suggested_job_type") or "").lower() == "ar_invoice"
    ]
    sales_classified_in_ap_folder = [
        r for r in sales_classified_in_ap_folder
        if AP_FOLDER_HINT_RE.search(r.get("square9_parent_path") or "")
    ]

    return {
        "total_bucket_A": len(enriched),
        "rows": enriched,
        "cohorts": cohorts,
        "root_cause_counts": dict(
            Counter(r["root_cause"] for r in enriched).most_common()
        ),
        "top_email_senders": Counter(
            (r.get("email_sender") or "<unknown>") for r in enriched
        ).most_common(25),
        "top_classification_methods": Counter(
            (r.get("classification_method") or "<unknown>") for r in enriched
        ).most_common(25),
        "top_routing_reasons": Counter(
            (r.get("routing_reason") or "<unknown>") for r in enriched
        ).most_common(25),
        "high_confidence_misrouted": high_conf_misrouted,
        "ap_doc_in_non_ap_mailbox": ap_doc_in_non_ap_mailbox,
        "sales_classified_in_ap_folder": sales_classified_in_ap_folder,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _exit_code(result: Dict[str, Any]) -> int:
    if result["total_bucket_A"] == 0:
        return 0
    actionable = (
        result["root_cause_counts"].get(
            "high_confidence_AP_invoice_misrouted", 0
        )
        + result["root_cause_counts"].get(
            "sales_mailbox_captured_AP_invoice", 0
        )
        + result["root_cause_counts"].get(
            "operations_mailbox_captured_AP_invoice", 0
        )
    )
    return 2 if actionable > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bucket A root cause analyzer (read-only).",
    )
    ap.add_argument("--resolved-csv",
                    default="prod_reports/square9_only_triage_resolved.csv")
    ap.add_argument("--out-csv",
                    default="prod_reports/bucket_A_root_cause.csv")
    ap.add_argument("--json",
                    default="prod_reports/bucket_A_root_cause.json")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    rows = load_resolved_bucket_A(args.resolved_csv)
    print(f"Loaded {len(rows)} Bucket A row(s) from {args.resolved_csv}",
          file=sys.stderr)

    doc_ids = [r.get("best_hub_doc_id") or "" for r in rows]
    print(f"Enriching {len(set(doc_ids))} distinct hub_doc_ids from Mongo...",
          file=sys.stderr)
    enrichment = enrich_from_hub(set(doc_ids))
    print(f"  enrichment hits: {len(enrichment)}", file=sys.stderr)

    result = analyze(rows, enrichment)
    write_csv(args.out_csv, result["rows"])

    summary = {
        "total_bucket_A": result["total_bucket_A"],
        "root_cause_counts": result["root_cause_counts"],
        "top_cohorts": result["cohorts"][:args.top],
        "top_email_senders": result["top_email_senders"][:args.top],
        "top_classification_methods": result["top_classification_methods"][:args.top],
        "top_routing_reasons": result["top_routing_reasons"][:args.top],
        "top_high_confidence_misrouted": [
            {k: r[k] for k in (
                "square9_name", "best_hub_doc_id", "best_hub_file_name",
                "best_hub_mailbox_category", "best_hub_doc_type",
                "best_hub_suggested_job_type", "email_sender",
                "best_match_score", "best_match_reason",
            )} for r in result["high_confidence_misrouted"][:25]
        ],
        "top_ap_doc_in_non_ap_mailbox": [
            {k: r[k] for k in (
                "square9_name", "best_hub_doc_id", "best_hub_mailbox_category",
                "best_hub_doc_type", "best_hub_suggested_job_type",
                "email_sender", "best_match_score",
            )} for r in result["ap_doc_in_non_ap_mailbox"][:25]
        ],
        "top_sales_classified_in_ap_folder": [
            {k: r[k] for k in (
                "square9_name", "square9_parent_path", "best_hub_doc_id",
                "best_hub_mailbox_category", "best_hub_doc_type",
                "best_hub_suggested_job_type", "email_sender",
            )} for r in result["sales_classified_in_ap_folder"][:25]
        ],
        "out_csv": args.out_csv,
    }
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)

    print()
    print("=== bucket_A_root_cause ===")
    print(f"  total_bucket_A:                    {result['total_bucket_A']}")
    for k, v in result["root_cause_counts"].items():
        print(f"  {k:34s} {v}")
    print()
    print(f"  TOP {min(args.top, len(result['cohorts']))} COHORTS:")
    for c in result["cohorts"][:args.top]:
        print(f"    n={c['count']:4d}  "
              f"sender={c['cohort_key']['email_sender']!r}  "
              f"cat={c['cohort_key']['best_hub_mailbox_category']!r}  "
              f"type={c['cohort_key']['best_hub_doc_type']!r}  "
              f"cls={c['cohort_key']['classification_method']!r}  "
              f"sq_root={c['cohort_key']['square9_parent_root']!r}  "
              f"causes={c['root_causes']}")
    print()
    print("  TOP 25 HIGH-CONFIDENCE MISROUTED (score>=0.90, AP_INVOICE in non-AP mailbox):")
    for r in result["high_confidence_misrouted"][:25]:
        print(f"    sq={r['square9_name']!r}  hub_id={r['best_hub_doc_id']!r}  "
              f"hub_cat={r['best_hub_mailbox_category']!r}  "
              f"sender={r['email_sender']!r}")
    print()
    print(f"  out_csv: {args.out_csv}")
    print(f"  json:    {args.json}")

    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
