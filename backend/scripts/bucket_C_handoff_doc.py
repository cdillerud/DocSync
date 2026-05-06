"""
bucket_C_handoff_doc.py
=======================
READ-ONLY generator for the Bucket C IT/AP handoff package.

Consumes:
  --plan-json   prod_reports/bucket_C_remediation_plan.json

Renders an operator-friendly handoff doc that groups every
``intake_channel_changes`` cohort by ``owner_hint`` (IT vs AP), plus a
``parity_exclusions`` section listing the doc-type buckets to drop from
the cutover parity denominator.

This script proposes nothing live — it does not touch the classifier,
the routing service, mailbox sources, transport rules, hub_documents,
or any production config.

Outputs:
  prod_reports/bucket_C_handoff.md     (human-readable, Markdown)
  prod_reports/bucket_C_handoff.csv    (one row per cohort/exclusion;
                                        importable into ticket trackers)

Exit codes:
  0  no plan rows OR plan has no cohorts at all
  1  plan has only parity_exclusions (no IT/AP intake-channel changes)
  2  at least one IT or AP intake-channel-change cohort emitted
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OWNER_ORDER = ["IT", "AP"]

CSV_COLUMNS = [
    "section",
    "owner_hint",
    "likely_vendor",
    "candidate_intake_channel",
    "doc_type_guess",
    "recommended_intake_change",
    "affected_doc_count",
    "top_square9_parent_root",
    "evidence_sample_count",
    "exclusion_reason",
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _norm(val: Any) -> str:
    return (val if isinstance(val, str) else ("" if val is None else str(val))).strip()


def _top_root(cohort: Dict[str, Any]) -> str:
    roots = cohort.get("top_square9_parent_roots") or []
    if not roots:
        return ""
    first = roots[0]
    if isinstance(first, (list, tuple)) and first:
        return _norm(first[0])
    if isinstance(first, dict):
        return _norm(first.get("parent_root") or first.get(0))
    return _norm(first)


def group_intake_by_owner(plan: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in plan.get("intake_channel_changes") or []:
        owner = _norm(c.get("owner_hint")) or "AP"
        grouped[owner].append(c)
    for owner in grouped:
        grouped[owner].sort(key=lambda c: -int(c.get("affected_doc_count") or 0))
    return grouped


# ---------------------------------------------------------------------------
# CSV rows
# ---------------------------------------------------------------------------

def cohort_to_csv_row(cohort: Dict[str, Any]) -> Dict[str, Any]:
    ck = cohort.get("cohort_key") or {}
    return {
        "section": "intake_channel_changes",
        "owner_hint": _norm(cohort.get("owner_hint")),
        "likely_vendor": _norm(ck.get("likely_vendor")),
        "candidate_intake_channel": _norm(ck.get("candidate_intake_channel")),
        "doc_type_guess": "",
        "recommended_intake_change": _norm(cohort.get("recommended_intake_change")),
        "affected_doc_count": int(cohort.get("affected_doc_count") or 0),
        "top_square9_parent_root": _top_root(cohort),
        "evidence_sample_count": len(cohort.get("evidence_sample") or []),
        "exclusion_reason": "",
    }


def exclusion_to_csv_row(cohort: Dict[str, Any]) -> Dict[str, Any]:
    ck = cohort.get("cohort_key") or {}
    return {
        "section": "parity_exclusions",
        "owner_hint": _norm(cohort.get("owner_hint")) or "AP",
        "likely_vendor": "",
        "candidate_intake_channel": "",
        "doc_type_guess": _norm(ck.get("doc_type_guess")),
        "recommended_intake_change": "exclude_from_parity_denominator",
        "affected_doc_count": int(cohort.get("affected_doc_count") or 0),
        "top_square9_parent_root": _top_root(cohort),
        "evidence_sample_count": len(cohort.get("evidence_sample") or []),
        "exclusion_reason": _norm(cohort.get("exclusion_reason")),
    }


def build_csv_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    grouped = group_intake_by_owner(plan)
    for owner in OWNER_ORDER:
        for c in grouped.get(owner, []):
            rows.append(cohort_to_csv_row(c))
    extra_owners = sorted(set(grouped) - set(OWNER_ORDER))
    for owner in extra_owners:
        for c in grouped[owner]:
            rows.append(cohort_to_csv_row(c))
    for c in plan.get("parity_exclusions") or []:
        rows.append(exclusion_to_csv_row(c))
    return rows


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def _evidence_first_name(cohort: Dict[str, Any]) -> str:
    sample = cohort.get("evidence_sample") or []
    if not sample:
        return ""
    return _norm(sample[0].get("square9_name") or sample[0].get("filename_pattern"))


def _render_owner_section(owner: str,
                          cohorts: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    out.append(f"## {owner} actions")
    out.append("")
    if not cohorts:
        out.append(f"_No {owner} cohorts in this plan._")
        out.append("")
        return out
    headers = [
        "vendor",
        "channel",
        "recommended change",
        "affected docs",
        "top Square9 root",
        "sample",
    ]
    table_rows = []
    for c in cohorts:
        ck = c.get("cohort_key") or {}
        table_rows.append([
            _norm(ck.get("likely_vendor")) or "<unknown>",
            _norm(ck.get("candidate_intake_channel")) or "unknown",
            _norm(c.get("recommended_intake_change")),
            int(c.get("affected_doc_count") or 0),
            _top_root(c) or "—",
            _evidence_first_name(c) or "—",
        ])
    out.append(_md_table(headers, table_rows))
    out.append("")
    out.append(f"### {owner} checklist")
    out.append("")
    for c in cohorts:
        ck = c.get("cohort_key") or {}
        vendor = _norm(ck.get("likely_vendor")) or "<unknown>"
        channel = _norm(ck.get("candidate_intake_channel")) or "unknown"
        rec = _norm(c.get("recommended_intake_change"))
        affected = int(c.get("affected_doc_count") or 0)
        out.append(
            f"- [ ] **{vendor}** — apply `{rec}` for channel `{channel}` "
            f"({affected} doc(s)); verify on the next mail-poll cycle."
        )
    out.append("")
    return out


def _render_exclusions(plan: Dict[str, Any]) -> List[str]:
    out: List[str] = ["## Parity exclusions (no action — drop from denominator)",
                      ""]
    excl = plan.get("parity_exclusions") or []
    if not excl:
        out.append("_No parity exclusions detected._")
        out.append("")
        return out
    headers = ["doc_type_guess", "exclusion_reason", "affected docs",
               "top Square9 root", "sample"]
    rows = []
    for c in excl:
        ck = c.get("cohort_key") or {}
        rows.append([
            _norm(ck.get("doc_type_guess")) or "unknown",
            _norm(c.get("exclusion_reason")) or "—",
            int(c.get("affected_doc_count") or 0),
            _top_root(c) or "—",
            _evidence_first_name(c) or "—",
        ])
    out.append(_md_table(headers, rows))
    out.append("")
    return out


def render_markdown(plan: Dict[str, Any],
                    grouped: Dict[str, List[Dict[str, Any]]],
                    generated_at: str) -> str:
    total_rows = int(plan.get("total_bucket_C_rows") or 0)
    intake_count = int(plan.get("intake_channel_change_cohort_count") or 0)
    excl_count = int(plan.get("parity_exclusion_cohort_count") or 0)
    it_count = len(grouped.get("IT", []))
    ap_count = len(grouped.get("AP", []))
    it_docs = sum(int(c.get("affected_doc_count") or 0)
                  for c in grouped.get("IT", []))
    ap_docs = sum(int(c.get("affected_doc_count") or 0)
                  for c in grouped.get("AP", []))

    body: List[str] = []
    body.append("# Bucket C — Hub Intake Handoff")
    body.append("")
    body.append(f"_Generated: {generated_at}_")
    body.append("")
    body.append("> **READ-ONLY:** this document is generated from the clean "
                "Bucket C remediation plan. Nothing in production has been "
                "changed by this report.")
    body.append("")
    body.append("## Summary")
    body.append("")
    body.append(_md_table(
        ["metric", "value"],
        [
            ["total Bucket C rows", total_rows],
            ["intake-channel-change cohorts", intake_count],
            ["parity-exclusion cohorts", excl_count],
            ["IT cohorts / docs", f"{it_count} / {it_docs}"],
            ["AP cohorts / docs", f"{ap_count} / {ap_docs}"],
        ],
    ))
    body.append("")

    for owner in OWNER_ORDER:
        body.extend(_render_owner_section(owner, grouped.get(owner, [])))

    extra = sorted(set(grouped) - set(OWNER_ORDER))
    for owner in extra:
        body.extend(_render_owner_section(owner, grouped[owner]))

    body.extend(_render_exclusions(plan))

    body.append("## Cutover checklist")
    body.append("")
    body.append("- [ ] All IT cohorts ticketed and assigned an owner")
    body.append("- [ ] All AP cohorts ticketed and assigned an owner")
    body.append("- [ ] Parity exclusions confirmed by AP lead")
    body.append("- [ ] Re-run "
                "`backend/scripts/square9_hub_ap_parity_report.py` post-fix")
    body.append("- [ ] Confirm match-rate ≥ 85% before Square9 cutover call")
    body.append("")
    return "\n".join(body)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def write_md(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})


def load_plan(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _exit_code(plan: Dict[str, Any],
               grouped: Dict[str, List[Dict[str, Any]]]) -> int:
    intake_count = int(plan.get("intake_channel_change_cohort_count") or 0)
    excl_count = int(plan.get("parity_exclusion_cohort_count") or 0)
    if intake_count == 0 and excl_count == 0:
        return 0
    if intake_count == 0 and excl_count > 0:
        return 1
    if not any(grouped.get(o) for o in OWNER_ORDER) and not grouped:
        return 1
    return 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(plan: Dict[str, Any],
                   grouped: Dict[str, List[Dict[str, Any]]],
                   md_path: str, csv_path: str) -> None:
    print()
    print("=== bucket_C_handoff_doc ===")
    print(f"  total_bucket_C_rows:                  {plan.get('total_bucket_C_rows')}")
    print(f"  intake_channel_change_cohort_count:   {plan.get('intake_channel_change_cohort_count')}")
    print(f"  parity_exclusion_cohort_count:        {plan.get('parity_exclusion_cohort_count')}")
    for owner in OWNER_ORDER:
        cohorts = grouped.get(owner, [])
        docs = sum(int(c.get("affected_doc_count") or 0) for c in cohorts)
        print(f"  {owner} cohorts/docs:                       {len(cohorts)} / {docs}")
    extra = sorted(set(grouped) - set(OWNER_ORDER))
    for owner in extra:
        cohorts = grouped[owner]
        docs = sum(int(c.get("affected_doc_count") or 0) for c in cohorts)
        print(f"  {owner} cohorts/docs (other):           {len(cohorts)} / {docs}")
    rec_counts = Counter(
        _norm(c.get("recommended_intake_change"))
        for cohorts in grouped.values() for c in cohorts
    ).most_common()
    if rec_counts:
        print()
        print("  recommended_intake_change_counts:")
        for k, v in rec_counts:
            print(f"    {v:4d}  {k}")
    print()
    print(f"  out_md:   {md_path}")
    print(f"  out_csv:  {csv_path}")
    print("  NOTE: dry-run only — no production change executed.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket C handoff doc generator (read-only).",
    )
    p.add_argument("--plan-json",
                   default="prod_reports/bucket_C_remediation_plan.json")
    p.add_argument("--out-md",
                   default="prod_reports/bucket_C_handoff.md")
    p.add_argument("--out-csv",
                   default="prod_reports/bucket_C_handoff.csv")
    args = p.parse_args()

    plan = load_plan(args.plan_json)
    print(
        f"Loaded plan from {args.plan_json}: "
        f"{plan.get('intake_channel_change_cohort_count')} intake cohort(s), "
        f"{plan.get('parity_exclusion_cohort_count')} exclusion cohort(s)",
        file=sys.stderr,
    )
    grouped = group_intake_by_owner(plan)
    generated_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    md_body = render_markdown(plan, grouped, generated_at)
    csv_rows = build_csv_rows(plan)
    write_md(args.out_md, md_body)
    write_csv(args.out_csv, csv_rows)
    _print_summary(plan, grouped, args.out_md, args.out_csv)
    return _exit_code(plan, grouped)


if __name__ == "__main__":
    raise SystemExit(main())
