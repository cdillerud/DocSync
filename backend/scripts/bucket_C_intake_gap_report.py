"""
bucket_C_intake_gap_report.py
=============================
READ-ONLY diagnostic. Consumes the resolved triage CSV produced by
`square9_only_triage_resolver.py` and analyzes Bucket C (Square9 has
the doc, Hub never received it) by clustering on Square9 parent path,
filename pattern, vendor token, and date token to surface candidate
intake-channel hypotheses.

Read-only. No code or routing changes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

# Patterns that indicate the doc is NOT a Hub-expected AP invoice.
# Order matters — most specific first (so e.g. "Monthly Rec & Templates"
# matches monthly_reconciliation rather than template_or_form).
NOT_HUB_EXPECTED_PATTERNS = (
    (re.compile(r"\.pst\b", re.IGNORECASE),
     "outlook_export"),
    (re.compile(r"\bAllocation\s*-\s*EM\b", re.IGNORECASE),
     "allocation_sheet"),
    (re.compile(r"\bDO\s*NOT\s*PAY\b", re.IGNORECASE),
     "do_not_pay_marker"),
    (re.compile(r"\bMonthly\s*Rec\b", re.IGNORECASE),
     "monthly_reconciliation"),
    (re.compile(r"\bExpected\s*Vendor\s*Credits?\b", re.IGNORECASE),
     "credits_report"),
    (re.compile(r"\bOrder\s*Issues?\s*Emails?\b", re.IGNORECASE),
     "internal_email_archive"),
    (re.compile(r"\bWork\s*Instructions?\b", re.IGNORECASE),
     "work_instructions"),
    (re.compile(r"\bPositive\s*Pay\b", re.IGNORECASE),
     "bank_positive_pay_file"),
    (re.compile(r"\bOutgoing\s*Wires?\b", re.IGNORECASE),
     "treasury_outgoing_wire"),
    # Generic — checked LAST so more-specific exclusions win first.
    (re.compile(r"\bTemplate(s)?\b", re.IGNORECASE),
     "template_or_form"),
)

# Vendor-name extraction from Square9 filename. Square9 names look like:
#   "<orderno>_VENDOR_<invoice>_<date>.pdf"
#   "_VENDOR_<...>.pdf"
#   "VENDOR <date> <invoice>.pdf"
# `_` is a word char in regex, so we use explicit alpha lookarounds rather
# than `\b` to anchor vendor matches across underscore-separated tokens.
VENDOR_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z&]{2,}", re.UNICODE)
DATE_TOKEN_RES = (
    # ISO with optional separators: 2026-04-15 / 2026_04_15 / 20260415
    re.compile(
        r"(?<!\d)(20\d{2}[-_/.]?(?:0[1-9]|1[0-2])[-_/.]?(?:0[1-9]|[12]\d|3[01]))(?!\d)"
    ),
    # US separated: 04-15-2026 / 04/15/26
    re.compile(
        r"(?<!\d)((?:0[1-9]|1[0-2])[-_/.](?:0[1-9]|[12]\d|3[01])[-_/.](?:20)?\d{2})(?!\d)"
    ),
    # Compact MMDDYYYY (8 digits) or MMDDYY (6 digits)
    re.compile(
        r"(?<!\d)((?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?:20\d{2}|\d{2}))(?!\d)"
    ),
    # Year-only fallback
    re.compile(r"(?<!\d)(20\d{2})(?!\d)"),
)
INVOICE_TOKEN_RE = re.compile(r"(?<!\d)(\d{4,})(?!\d)")

# Vendor-name boundary helper that treats `_` as a separator.
def _vp(name: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<![A-Za-z]){name}(?![A-Za-z])", re.IGNORECASE)


# Patterns that DO look like AP invoices, useful when nothing matches the
# exclusion patterns. Each tuple is (regex, hypothesized intake channel,
# recommended action).
AP_VENDOR_HINT_PATTERNS = (
    (_vp("FedEx"),
     "fedex_billing_email", "add_fedex_sender_to_AP_intake"),
    (_vp("Cogent"),
     "cogent_billing_portal", "investigate_cogent_portal_or_email_rule"),
    (_vp("RLCarriers"),
     "rl_carriers_email", "confirm_rl_forward_to_AP_mailbox"),
    (_vp("OIPkgSol"),
     "oi_packaging_solutions_email", "add_oi_pkg_sender_to_AP_intake"),
    (_vp("Britton"),
     "britton_email", "confirm_britton_sender_in_AP_flow"),
    (_vp("Boyer"),
     "boyer_email", "confirm_boyer_sender_in_AP_flow"),
    (_vp("Hawkemedia"),
     "hawkemedia_email", "confirm_hawkemedia_sender_in_AP_flow"),
    (_vp("MDI"),
     "mdi_email", "confirm_mdi_sender_in_AP_flow"),
    (_vp("MRA"),
     "mra_email", "confirm_mra_sender_in_AP_flow"),
    (_vp("ClosureSystems"),
     "closure_systems_email", "confirm_closure_sender_in_AP_flow"),
    (_vp("TDLINES"),
     "tdlines_email", "confirm_tdlines_sender_in_AP_flow"),
)


def classify_intake(name: str, parent_path: str
                    ) -> Tuple[str, str, str, str]:
    """Returns (intake_channel, recommended_action, doc_type_guess,
    likely_vendor)."""
    blob = f"{name} {parent_path}"

    for pat, label in NOT_HUB_EXPECTED_PATTERNS:
        if pat.search(blob):
            return ("not_expected_in_hub", "exclude_from_parity_denominator",
                    label, "")

    for pat, channel, action in AP_VENDOR_HINT_PATTERNS:
        m = pat.search(blob)
        if m:
            return (channel, action, "ap_invoice_candidate", m.group(0))

    # Square9 filename schema: "_VENDOR_..." or "<order>_VENDOR_..."
    base = name.rsplit(".", 1)[0] if "." in name else name
    parts = re.split(r"[_\-]", base)
    vendor_guess = ""
    for part in parts:
        # vendor is alphabetic, length >= 3, not a date or pure digit
        if (
            len(part) >= 3
            and VENDOR_TOKEN_RE.fullmatch(part) is not None
            and not part.isdigit()
            and part.upper() not in ("PDF", "INV", "INVOICE", "BILL")
        ):
            vendor_guess = part
            break

    # If parent path implies a real AP folder lane, it's an AP candidate
    if re.search(r"(Misc Invoices|Warehouse|Dropship|Freight|S&H Invoices|"
                 r"Vendor Credit|Ball Orders)", parent_path, re.IGNORECASE):
        return ("monitored_ap_lane_unknown_sender",
                "investigate_intake_for_this_vendor",
                "ap_invoice_candidate", vendor_guess)

    return ("unknown", "investigate", "unknown", vendor_guess)


def _root_segment(path: str) -> str:
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
    if not parts:
        return ""
    if parts[0].lower() == "temp folder" and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _filename_pattern(name: str) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    tokens = re.findall(r"[A-Za-z]{3,}", base)
    return " ".join(t.upper() for t in tokens[:6])


def _extract_date_token(name: str) -> str:
    for pat in DATE_TOKEN_RES[:3]:
        m = pat.search(name)
        if m:
            return m.group(0)
    return ""


def _extract_invoice_token(name: str) -> str:
    for m in INVOICE_TOKEN_RE.finditer(name):
        tok = m.group(0)
        if not (len(tok) == 4 and 2018 <= int(tok) <= 2035):
            return tok
    return ""


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "square9_name", "square9_parent_path", "square9_parent_root",
    "square9_modified", "filename_pattern", "likely_vendor",
    "date_token", "invoice_token", "doc_type_guess",
    "candidate_intake_channel", "recommended_action", "is_parity_exclusion",
]


def load_resolved_bucket_C(path: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("bucket") or "").strip().upper() == "C":
                out.append(r)
    return out


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    enriched: List[Dict[str, Any]] = []
    for r in rows:
        name = r.get("square9_name") or ""
        parent = r.get("square9_parent_path") or ""
        channel, action, doc_guess, vendor = classify_intake(name, parent)
        enriched.append({
            "square9_name": name,
            "square9_parent_path": parent,
            "square9_parent_root": _root_segment(parent),
            "square9_modified": r.get("square9_modified") or "",
            "filename_pattern": _filename_pattern(name),
            "likely_vendor": vendor,
            "date_token": _extract_date_token(name),
            "invoice_token": _extract_invoice_token(name),
            "doc_type_guess": doc_guess,
            "candidate_intake_channel": channel,
            "recommended_action": action,
            "is_parity_exclusion": (
                channel == "not_expected_in_hub"
            ),
        })

    n_total = len(enriched)
    n_exclusions = sum(1 for r in enriched if r["is_parity_exclusion"])
    n_real_gaps = n_total - n_exclusions

    return {
        "total_bucket_C": n_total,
        "rows": enriched,
        "parity_exclusion_count": n_exclusions,
        "real_intake_gap_count": n_real_gaps,
        "intake_channel_counts": dict(
            Counter(r["candidate_intake_channel"] for r in enriched).most_common()
        ),
        "doc_type_guess_counts": dict(
            Counter(r["doc_type_guess"] for r in enriched).most_common()
        ),
        "top_unmatched_folders": Counter(
            r["square9_parent_root"] for r in enriched
            if not r["is_parity_exclusion"]
        ).most_common(25),
        "top_unmatched_vendors": Counter(
            (r["likely_vendor"] or "<unknown>") for r in enriched
            if not r["is_parity_exclusion"]
        ).most_common(25),
        "top_filename_patterns": Counter(
            r["filename_pattern"] for r in enriched
            if not r["is_parity_exclusion"]
        ).most_common(25),
        "parity_exclusion_rows": [r for r in enriched if r["is_parity_exclusion"]],
        "real_intake_gap_rows": [r for r in enriched if not r["is_parity_exclusion"]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _exit_code(result: Dict[str, Any]) -> int:
    if result["total_bucket_C"] == 0:
        return 0
    if result["real_intake_gap_count"] == 0:
        return 1
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bucket C intake gap analyzer (read-only).",
    )
    ap.add_argument("--resolved-csv",
                    default="prod_reports/square9_only_triage_resolved.csv")
    ap.add_argument("--out-csv",
                    default="prod_reports/bucket_C_intake_gap.csv")
    ap.add_argument("--json",
                    default="prod_reports/bucket_C_intake_gap.json")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    rows = load_resolved_bucket_C(args.resolved_csv)
    print(f"Loaded {len(rows)} Bucket C row(s) from {args.resolved_csv}",
          file=sys.stderr)

    result = analyze(rows)
    write_csv(args.out_csv, result["rows"])

    summary = {
        "total_bucket_C": result["total_bucket_C"],
        "parity_exclusion_count": result["parity_exclusion_count"],
        "real_intake_gap_count": result["real_intake_gap_count"],
        "intake_channel_counts": result["intake_channel_counts"],
        "doc_type_guess_counts": result["doc_type_guess_counts"],
        "top_unmatched_folders": result["top_unmatched_folders"][:args.top],
        "top_unmatched_vendors": result["top_unmatched_vendors"][:args.top],
        "top_filename_patterns": result["top_filename_patterns"][:args.top],
        "top_real_intake_gap_examples": [
            {k: r[k] for k in (
                "square9_name", "square9_parent_path", "square9_modified",
                "likely_vendor", "candidate_intake_channel",
                "recommended_action",
            )} for r in result["real_intake_gap_rows"][:args.top]
        ],
        "top_parity_exclusion_examples": [
            {k: r[k] for k in (
                "square9_name", "square9_parent_path",
                "candidate_intake_channel", "doc_type_guess",
                "recommended_action",
            )} for r in result["parity_exclusion_rows"][:args.top]
        ],
        "out_csv": args.out_csv,
    }
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)

    print()
    print("=== bucket_C_intake_gap ===")
    print(f"  total_bucket_C:                {result['total_bucket_C']}")
    print(f"  parity_exclusion_count:        {result['parity_exclusion_count']}  "
          "(treasury/template/PST/DO NOT PAY/etc.)")
    print(f"  real_intake_gap_count:         {result['real_intake_gap_count']}  "
          "(Hub should receive these but doesn't)")
    print()
    print("  intake_channel_counts:")
    for ch, n in result["intake_channel_counts"].items():
        print(f"    {n:4d}  {ch}")
    print()
    print(f"  TOP {args.top} REAL INTAKE GAPS:")
    for r in result["real_intake_gap_rows"][:args.top]:
        print(f"    {r['square9_name']!r}  "
              f"parent={r['square9_parent_root']!r}  "
              f"vendor={r['likely_vendor']!r}  "
              f"channel={r['candidate_intake_channel']!r}  "
              f"action={r['recommended_action']!r}")
    print()
    print("  TOP UNMATCHED FOLDERS:")
    for path, n in result["top_unmatched_folders"][:args.top]:
        print(f"    {n:4d}  {path!r}")
    print()
    print("  TOP UNMATCHED VENDORS:")
    for v, n in result["top_unmatched_vendors"][:args.top]:
        print(f"    {n:4d}  {v!r}")
    print()
    print("  PARITY EXCLUSIONS (will be excluded from cutover denominator):")
    for r in result["parity_exclusion_rows"][:args.top]:
        print(f"    {r['square9_name']!r}  reason={r['doc_type_guess']!r}")
    print()
    print(f"  out_csv: {args.out_csv}")
    print(f"  json:    {args.json}")

    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
