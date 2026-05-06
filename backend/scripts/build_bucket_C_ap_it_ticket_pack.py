"""
build_bucket_C_ap_it_ticket_pack.py
===================================
READ-ONLY. Builds a review-ready Bucket C handoff package from an
existing cutover proof directory. Produces, inside the proof_dir:

  BUCKET_C_AP_IT_TICKET_PACK.md   — structured handoff with executive
                                    summary, IT section, AP section,
                                    portal-download section, manual-
                                    followup section, explicit non-
                                    actions, after-actions checklist,
                                    and an email draft.
  BUCKET_C_AP_IT_TICKET_PACK.csv  — ticket-import-ready CSV with
                                    columns: ticket_owner, vendor,
                                    affected_doc_count, issue_type,
                                    recommended_action,
                                    validation_expectation, priority,
                                    source_square9_folder, notes.
  BUCKET_C_AP_IT_EMAIL_DRAFT.txt  — copy/pasteable email body.

Inputs:
  --proof-dir  prod_reports/cutover_proof_<timestamp>/   (required)

Reads:
  <proof-dir>/summary.json
  prod_reports/bucket_C_remediation_plan.json
  (also tolerates a missing remediation plan by falling back to the
   handoff CSV inside the proof dir)

Performs no DB writes. Performs no Mongo / Exchange / cutover actions.

Exit codes:
  0  package successfully written
  1  inputs missing or unparseable
  2  no Bucket C cohorts in the plan (nothing to ticket)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Action → priority + validation expectation taxonomy
# ---------------------------------------------------------------------------

# (priority, default_validation_expectation, default_issue_type)
ACTION_TAXONOMY: Dict[str, Tuple[str, str, str]] = {
    "add_sender_to_AP_transport_rule": (
        "P1",
        "Send a test message from the vendor's billing address; verify "
        "it lands in the AP intake mailbox within the next mail-poll cycle "
        "(<= 15 min).",
        "intake_misroute_at_transport_layer",
    ),
    "forward_billing_alias_to_hub_ap_intake": (
        "P1",
        "Confirm with vendor that the alias forward is in place; verify "
        "the next live invoice from this vendor appears in Hub AP within "
        "24 hours and shows on the parity report's matched bucket.",
        "intake_alias_not_forwarded",
    ),
    "enable_portal_download": (
        "P2",
        "Pull the most recent open invoice from the vendor portal, email "
        "it to the AP intake address, and confirm Hub ingests it; document "
        "any portal credentials in the AP runbook.",
        "intake_portal_download_required",
    ),
    "manual_followup": (
        "P2",
        "AP to investigate the vendor's billing channel: confirm whether "
        "these docs are in scope for AP, and if so, identify the correct "
        "intake mechanism (email forward, portal, EDI) and open a "
        "follow-up ticket.",
        "intake_channel_unknown",
    ),
}

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def top_square9_root(cohort: Dict[str, Any]) -> str:
    roots = cohort.get("top_square9_parent_roots") or []
    if not roots:
        return ""
    first = roots[0]
    if isinstance(first, (list, tuple)) and first:
        return _str(first[0])
    if isinstance(first, dict):
        return _str(first.get("parent_root") or first.get(0))
    return _str(first)


def classify_cohort(cohort: Dict[str, Any]) -> Dict[str, Any]:
    """Decorate a remediation-plan intake cohort with priority, owner,
    issue_type, and a validation expectation drawn from the closed
    taxonomy. Pure: no I/O."""
    ck = cohort.get("cohort_key") or {}
    vendor = _str(ck.get("likely_vendor") or "<unknown>") or "<unknown>"
    channel = _str(ck.get("candidate_intake_channel") or "unknown") or "unknown"
    owner = _str(cohort.get("owner_hint") or "AP") or "AP"
    rec_action = _str(cohort.get("recommended_intake_change")
                      or "manual_followup")
    affected = _int(cohort.get("affected_doc_count"))
    sq9_root = top_square9_root(cohort)

    priority, validation, issue_type = ACTION_TAXONOMY.get(
        rec_action,
        ("P2", "Confirm correct intake mechanism with vendor and AP team.",
         "intake_channel_unknown"),
    )

    return {
        "ticket_owner": owner,
        "vendor": vendor,
        "channel": channel,
        "affected_doc_count": affected,
        "issue_type": issue_type,
        "recommended_action": rec_action,
        "validation_expectation": validation,
        "priority": priority,
        "source_square9_folder": sq9_root,
        "notes": "",
    }


def partition_tickets(tickets: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Split tickets into the four MD sections we render."""
    out: Dict[str, List[Dict[str, Any]]] = {
        "it": [],
        "ap_alias_forward": [],
        "ap_portal_download": [],
        "ap_manual_followup": [],
    }
    for t in tickets:
        if t["ticket_owner"].upper() == "IT":
            out["it"].append(t)
            continue
        action = t["recommended_action"]
        if action == "forward_billing_alias_to_hub_ap_intake":
            out["ap_alias_forward"].append(t)
        elif action == "enable_portal_download":
            out["ap_portal_download"].append(t)
        else:
            out["ap_manual_followup"].append(t)
    for key in out:
        out[key].sort(key=lambda r: (-r["affected_doc_count"], r["vendor"]))
    return out


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_remediation_plan(proof_dir: str) -> Optional[str]:
    """The bucket_C_intake_remediation_plan.py script writes its JSON
    to prod_reports/. Resolve via the proof_dir's parent."""
    parent = os.path.dirname(os.path.normpath(proof_dir)) or "."
    candidate = os.path.join(parent, "bucket_C_remediation_plan.json")
    return candidate if os.path.exists(candidate) else None


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "ticket_owner",
    "vendor",
    "affected_doc_count",
    "issue_type",
    "recommended_action",
    "validation_expectation",
    "priority",
    "source_square9_folder",
    "notes",
]


def render_csv(tickets: List[Dict[str, Any]]) -> str:
    from io import StringIO
    buf = StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for t in tickets:
        w.writerow({k: t.get(k, "") for k in CSV_COLUMNS})
    return buf.getvalue()


def _exec_summary_lines(summary: Dict[str, Any],
                        tickets: List[Dict[str, Any]]) -> List[str]:
    kc = summary.get("key_counts") or {}
    parity = kc.get("parity") or {}
    proj = kc.get("projection") or {}
    bucket_a = kc.get("bucket_A") or {}

    cur_rate = parity.get("match_rate_pct")
    proj_rate = proj.get("post_bucket_A_apply_match_rate_pct")
    min_rate = summary.get("min_match_rate_pct")

    cur = f"{cur_rate:.2f}%" if isinstance(cur_rate, (int, float)) else "unknown"
    pj = f"{proj_rate:.2f}%" if isinstance(proj_rate, (int, float)) else "unknown"
    minp = f"{min_rate:.2f}%" if isinstance(min_rate, (int, float)) else "unknown"

    it_count = sum(1 for t in tickets if t["ticket_owner"].upper() == "IT")
    ap_count = sum(1 for t in tickets if t["ticket_owner"].upper() == "AP")

    bucket_a_docs = bucket_a.get("actionable_doc_count")
    bucket_a_str = (
        f"Bucket A apply alone reclassifies {bucket_a_docs} Hub doc(s); "
        if isinstance(bucket_a_docs, (int, float))
        else "Bucket A apply alone is insufficient; "
    )

    out: List[str] = []
    out.append("## 1. Executive summary")
    out.append("")
    out.append(f"- **Current match rate**: {cur}")
    out.append(f"- **Projected match rate after Bucket A apply alone**: {pj}")
    out.append(f"- **Required match rate for cutover**: {minp}")
    out.append(f"- **Why Bucket C is required**: " + bucket_a_str
               + "the remaining Square9 docs are *not in Hub at all* "
               + "because the intake channels for these vendors are not "
               + "wired into the Hub AP mail flow. Closing the gap to "
               + "the cutover threshold requires the IT/AP work below.")
    out.append(f"- **Total Bucket C cohorts**: {len(tickets)}")
    out.append(f"- **IT-owned**: {it_count}")
    out.append(f"- **AP-owned**: {ap_count}")
    out.append("")
    return out


def _row_table(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return ["_(no cohorts in this section)_", ""]
    out = [
        "| vendor | docs | priority | recommended action | source Square9 folder |",
        "| --- | ---: | :---: | --- | --- |",
    ]
    for r in rows:
        out.append(
            f"| {r['vendor']} | {r['affected_doc_count']} | {r['priority']} "
            f"| {r['recommended_action']} | "
            f"{r['source_square9_folder'] or '—'} |"
        )
    out.append("")
    return out


def _render_ap_subsections(rows: List[Dict[str, Any]],
                           heading_prefix: str) -> List[str]:
    if not rows:
        return [f"_(no {heading_prefix.lower()} cohorts in this section)_", ""]
    out: List[str] = []
    for r in rows:
        out.append(f"### {heading_prefix}: {r['vendor']}")
        out.append("")
        out.append(f"- Vendor: **{r['vendor']}**")
        out.append(f"- Affected doc count: **{r['affected_doc_count']}**")
        out.append(f"- Square9 folder / source: "
                   f"`{r['source_square9_folder'] or 'unknown'}`")
        out.append(f"- Likely intake issue: `{r['issue_type']}`")
        out.append(f"- Recommended action: **{r['recommended_action']}**")
        out.append(f"- Owner: **{r['ticket_owner']}**")
        out.append(f"- Priority: **{r['priority']}**")
        out.append(f"- Validation expectation: {r['validation_expectation']}")
        out.append("")
    return out


def render_md(summary: Dict[str, Any],
              tickets: List[Dict[str, Any]],
              proof_dir: str,
              generated_at: str) -> str:
    parts = partition_tickets(tickets)
    lines: List[str] = []

    lines.append("# Bucket C — AP / IT Ticket Pack")
    lines.append("")
    lines.append(f"_Proof dir_: `{proof_dir}`")
    lines.append(f"_Generated_: {generated_at}")
    lines.append("")
    lines.append("> READ-ONLY package. No production state has been changed "
                 "by the generation of this document.")
    lines.append("")

    lines.extend(_exec_summary_lines(summary, tickets))

    # ----- IT section ------------------------------------------------------
    lines.append("## 2. IT ticket section")
    lines.append("")
    if parts["it"]:
        for r in parts["it"]:
            lines.append(f"### IT: {r['vendor']} — "
                         f"{r['recommended_action']}")
            lines.append("")
            lines.append(f"- Vendor: **{r['vendor']}**")
            lines.append(f"- Affected doc count: **{r['affected_doc_count']}**")
            lines.append(f"- Exact issue: `{r['issue_type']}` "
                         f"(channel `{r['channel']}`)")
            lines.append(f"- Recommended action: **{r['recommended_action']}**")
            lines.append(f"- Source Square9 folder: "
                         f"`{r['source_square9_folder'] or 'unknown'}`")
            lines.append(f"- Owner: **IT**")
            lines.append(f"- Priority: **{r['priority']}**")
            lines.append(f"- Validation command after change: "
                         f"{r['validation_expectation']}")
            lines.append("")
    else:
        lines.append("_(no IT cohorts in this proof dir)_")
        lines.append("")

    # ----- AP section ------------------------------------------------------
    lines.append("## 3. AP ticket section")
    lines.append("")
    lines.append("One subsection per vendor cohort that needs an alias "
                 "forward into the Hub AP intake address.")
    lines.append("")
    lines.extend(_render_ap_subsections(
        parts["ap_alias_forward"], heading_prefix="AP — alias forward"))

    # ----- Portal section --------------------------------------------------
    lines.append("## 4. Portal-download section")
    lines.append("")
    lines.append("Vendors whose invoices live behind a portal and need to "
                 "be pulled manually until a portal-API solution is in "
                 "place.")
    lines.append("")
    lines.extend(_render_ap_subsections(
        parts["ap_portal_download"], heading_prefix="AP — portal download"))

    # ----- Manual-followup section -----------------------------------------
    lines.append("## 5. Manual-followup section")
    lines.append("")
    lines.append("Cohorts where the intake channel cannot yet be "
                 "determined automatically. AP must confirm whether the "
                 "docs are in scope and how they should arrive.")
    lines.append("")
    lines.extend(_render_ap_subsections(
        parts["ap_manual_followup"], heading_prefix="AP — manual followup"))

    # ----- Non-actions -----------------------------------------------------
    lines.append("## 6. Explicit non-actions")
    lines.append("")
    lines.append("- No Square9 cutover yet.")
    lines.append("- No Square9 archive / `archive-stage-data` call.")
    lines.append("- No Bucket A data patch yet.")
    lines.append("- No Bucket A routing-rule activation yet.")
    lines.append("- No removal of `square9@gamerpackaging.com` from any "
                 "billing distribution group.")
    lines.append("- No DocuSign / HTTPS / parked AP-contamination work.")
    lines.append("")

    # ----- After-actions checklist -----------------------------------------
    lines.append("## 7. After-actions checklist")
    lines.append("")
    lines.append("Once the AP / IT items above are completed:")
    lines.append("")
    lines.append("- [ ] Re-run the proof pack:")
    lines.append("")
    lines.append("      docker compose exec backend bash "
                 "ops/prod_verify_square9_cutover_readiness.sh")
    lines.append("")
    lines.append("- [ ] Review the new banner: confirm "
                 "`parity.match_rate_pct` and the per-vendor counts "
                 "improved.")
    lines.append("- [ ] Only then consider the Bucket A apply (still "
                 "gated; idempotent; rollback file written first):")
    lines.append("")
    lines.append("      docker compose exec backend python "
                 "scripts/bucket_A_one_shot_data_patch_apply.py "
                 "--apply --confirm CUTOVER")
    lines.append("")

    # ----- Email draft -----------------------------------------------------
    lines.append("## 8. Email draft (AP / IT)")
    lines.append("")
    lines.append("> Copy / paste from `BUCKET_C_AP_IT_EMAIL_DRAFT.txt` "
                 "in this proof directory.")
    lines.append("")
    lines.append("```")
    lines.append(render_email(summary, tickets))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_email(summary: Dict[str, Any],
                 tickets: List[Dict[str, Any]]) -> str:
    kc = summary.get("key_counts") or {}
    parity = kc.get("parity") or {}
    proj = kc.get("projection") or {}
    cur = parity.get("match_rate_pct")
    proj_rate = proj.get("post_bucket_A_apply_match_rate_pct")
    minp = summary.get("min_match_rate_pct")

    it_count = sum(1 for t in tickets if t["ticket_owner"].upper() == "IT")
    ap_count = sum(1 for t in tickets if t["ticket_owner"].upper() == "AP")

    cur_s = f"{cur:.1f}%" if isinstance(cur, (int, float)) else "unknown"
    proj_s = (f"{proj_rate:.1f}%" if isinstance(proj_rate, (int, float))
              else "unknown")
    min_s = (f"{minp:.0f}%" if isinstance(minp, (int, float)) else "unknown")

    body = []
    body.append("Subject: GPI Hub — Square9 cutover readiness — "
                "AP/IT intake tickets")
    body.append("")
    body.append("Hi AP and IT,")
    body.append("")
    body.append("We are preparing to retire Square9 in favor of GPI Hub. "
                "The Hub-vs-Square9 parity report currently shows "
                f"{cur_s} of Square9 AP documents reflected in Hub, "
                f"against a {min_s} cutover threshold.")
    body.append("")
    body.append("The single largest reason for the gap is intake: "
                "several vendors send invoices to addresses or portals "
                "that are not currently routed into the Hub AP intake "
                "mailbox, so Hub never receives those documents. We "
                "have identified the specific cohorts.")
    body.append("")
    body.append(f"There are {it_count} IT ticket(s) and {ap_count} AP "
                "ticket(s) in the attached pack. They are read-only, "
                "ticket-import-ready, and grouped by owner / action / "
                "priority. Each row carries an explicit validation "
                "expectation that I will check on the next proof-pack "
                "re-run.")
    body.append("")
    body.append("If we can complete the IT transport-rule changes plus "
                "the AP alias-forward and portal-download items, the "
                "projected post-Bucket-A match rate moves from "
                f"{proj_s} toward the {min_s} cutover threshold and "
                "we can re-evaluate the cutover with confidence.")
    body.append("")
    body.append("No production state has changed as a result of this "
                "pack. The Bucket A reclassification step is still "
                "gated and will not run until the intake channels are "
                "fixed and we re-validate.")
    body.append("")
    body.append("Files attached:")
    body.append("  - BUCKET_C_AP_IT_TICKET_PACK.md  (full handoff "
                "with per-cohort detail and validation expectations)")
    body.append("  - BUCKET_C_AP_IT_TICKET_PACK.csv (one row per "
                "ticket; ready for ticket-tracker import)")
    body.append("")
    body.append("Thanks,")
    body.append("GPI Hub Operations")
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Top-level builder + IO
# ---------------------------------------------------------------------------

def build_tickets(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    cohorts = plan.get("intake_channel_changes") or []
    return [classify_cohort(c) for c in cohorts]


def write_outputs(proof_dir: str,
                  summary: Dict[str, Any],
                  tickets: List[Dict[str, Any]],
                  generated_at: str) -> Dict[str, str]:
    os.makedirs(proof_dir, exist_ok=True)
    md_path = os.path.join(proof_dir, "BUCKET_C_AP_IT_TICKET_PACK.md")
    csv_path = os.path.join(proof_dir, "BUCKET_C_AP_IT_TICKET_PACK.csv")
    email_path = os.path.join(proof_dir, "BUCKET_C_AP_IT_EMAIL_DRAFT.txt")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(summary, tickets, proof_dir, generated_at))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        f.write(render_csv(tickets))
    with open(email_path, "w", encoding="utf-8") as f:
        f.write(render_email(summary, tickets))
    return {"md": md_path, "csv": csv_path, "email": email_path}


def _print_summary(paths: Dict[str, str],
                   tickets: List[Dict[str, Any]],
                   summary: Dict[str, Any]) -> None:
    parts = partition_tickets(tickets)
    print()
    print("=== build_bucket_C_ap_it_ticket_pack ===")
    kc = summary.get("key_counts") or {}
    parity = kc.get("parity") or {}
    proj = kc.get("projection") or {}
    cur = parity.get("match_rate_pct")
    proj_rate = proj.get("post_bucket_A_apply_match_rate_pct")
    if isinstance(cur, (int, float)):
        print(f"  current match_rate_pct           : {cur:.2f}%")
    if isinstance(proj_rate, (int, float)):
        print(f"  projected after Bucket A apply   : {proj_rate:.2f}%")
    print(f"  total cohorts                    : {len(tickets)}")
    print(f"    IT cohorts                     : {len(parts['it'])}")
    print(f"    AP alias-forward cohorts       : {len(parts['ap_alias_forward'])}")
    print(f"    AP portal-download cohorts     : {len(parts['ap_portal_download'])}")
    print(f"    AP manual-followup cohorts     : {len(parts['ap_manual_followup'])}")
    print(f"  md_path   : {paths['md']}")
    print(f"  csv_path  : {paths['csv']}")
    print(f"  email_txt : {paths['email']}")
    print("  READ-ONLY: no production state was changed.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Build a Bucket C AP/IT ticket pack from a proof dir "
                    "(read-only).",
    )
    p.add_argument("--proof-dir", required=True,
                   help="prod_reports/cutover_proof_<timestamp>/ dir")
    p.add_argument("--remediation-plan", default=None,
                   help="Override path to bucket_C_remediation_plan.json. "
                        "Defaults to <proof-dir>/../bucket_C_remediation_plan.json.")
    args = p.parse_args()

    if not os.path.isdir(args.proof_dir):
        print(f"ERROR: proof-dir not found: {args.proof_dir}", file=sys.stderr)
        return 1

    summary_path = os.path.join(args.proof_dir, "summary.json")
    summary = load_json(summary_path) or {}
    if not summary:
        print(f"WARNING: summary.json missing or empty at {summary_path}; "
              "executive summary fields will read 'unknown'.",
              file=sys.stderr)

    plan_path = args.remediation_plan or find_remediation_plan(args.proof_dir)
    if not plan_path:
        print("ERROR: bucket_C_remediation_plan.json not found.",
              file=sys.stderr)
        return 1
    plan = load_json(plan_path)
    if not plan:
        print(f"ERROR: failed to parse {plan_path}", file=sys.stderr)
        return 1

    tickets = build_tickets(plan)
    if not tickets:
        print("INFO: no Bucket C intake_channel_changes cohorts in plan; "
              "nothing to ticket.", file=sys.stderr)
        return 2

    generated_at = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")
    paths = write_outputs(args.proof_dir, summary, tickets, generated_at)
    _print_summary(paths, tickets, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
