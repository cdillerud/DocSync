"""
ops/cutover_proof_summary.py
============================
Post-run summarizer for ``ops/prod_verify_square9_cutover_readiness.sh``.

READ-ONLY. Consumes the manifest produced by the bash orchestrator,
plus any parity / remediation report JSONs the orchestrator wrote into
the same proof directory. Emits:

  <proof_dir>/summary.json
  <proof_dir>/summary.md

…and prints a final GO / NO-GO block to stdout.

Decision matrix (deliberately strict and explicit):

  GO   = every step rc <= 2  AND  match_rate_pct >= --min-match-rate
  NO-GO otherwise; blockers list every failing condition.

Step exit-code interpretation (matches existing scripts in this repo):
  0 / 1 / 2 = completed (workflow-state signal — not a failure)
  >= 3      = real error; counted as a step failure / blocker
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

DEFAULT_MIN_MATCH_RATE = 85.0


# ---------------------------------------------------------------------------
# Manifest / parity loaders (pure, easy to fixture in tests)
# ---------------------------------------------------------------------------

def load_manifest(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_parity_match_rate(proof_dir: str) -> Optional[float]:
    """Best-effort: pulls match_rate_pct from the parity-report JSON if
    the orchestrator dumped one alongside the manifest. Returns None if
    no parity JSON is present or it lacks the field.

    Tolerates the parity script's mixed stdout/stderr capture: when run
    with ``--json`` the script prints a few lines of progress prose
    before the JSON blob, so we scan for the first ``{`` and parse from
    there.
    """
    candidates = [
        os.path.join(proof_dir, "square9_hub_ap_parity.json"),
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.json"),
        # The orchestrator runs the parity script with `--json`, which
        # prints a JSON blob to stdout. The orchestrator captures stdout
        # AND stderr into the per-step log file, so the .log starts with
        # progress prose (Graph token, Square9 listing, doc counts) and
        # only THEN contains a valid JSON object. Scan for the first
        # opening brace before parsing.
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.log"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        payload = _try_parse_json_file(p)
        if payload is None:
            continue
        rate = _extract_match_rate(payload)
        if rate is not None:
            return rate
    return None


def _try_parse_json_file(path: str) -> Optional[Any]:
    """Parse ``path`` as JSON. If strict parsing fails, fall back to
    parsing from the first line that begins with ``{`` to the end of
    file (handles parity-log preamble lines)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            tail = "\n".join(lines[i:])
            try:
                return json.loads(tail)
            except json.JSONDecodeError:
                return None
    return None


def _extract_match_rate(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    for key in ("match_rate_pct", "match_rate_percent", "match_rate"):
        if key in payload:
            try:
                val = float(payload[key])
            except (TypeError, ValueError):
                continue
            return val * 100.0 if val <= 1.0 and key == "match_rate" else val
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return _extract_match_rate(summary)
    return None


# ---------------------------------------------------------------------------
# Key counts (parity buckets, Bucket A / C cohort numbers, projection)
# ---------------------------------------------------------------------------

def load_parity_payload(proof_dir: str) -> Optional[Dict[str, Any]]:
    """Returns the parity report's full JSON payload (not just the
    match rate). Used for bucket_counts and the apply-step projection."""
    candidates = [
        os.path.join(proof_dir, "square9_hub_ap_parity.json"),
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.json"),
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.log"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        payload = _try_parse_json_file(p)
        if isinstance(payload, dict):
            return payload
    return None


def load_remediation_plan(path: str) -> Optional[Dict[str, Any]]:
    """Loads a remediation-plan JSON. Returns None on missing / parse failure."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# Match-bucket keys treated as "this Square9 doc IS reflected in Hub".
# Mirrors square9_hub_ap_parity_report.py's match-rate formula:
#   matched = exact_match + strong_evidence_match + likely_match + possible_match
MATCHED_BUCKET_KEYS = (
    "exact_match",
    "strong_evidence_match",
    "likely_match",
    "possible_match",
)


def _derive_matched_count(bucket_counts: Dict[str, Any]) -> Optional[int]:
    """Sum the four match buckets. Honors a precomputed `matched` key
    if the parity script ever emits one, otherwise sums the constituent
    buckets. Returns None when the data is unusable."""
    if not isinstance(bucket_counts, dict):
        return None
    if isinstance(bucket_counts.get("matched"), (int, float)):
        return int(bucket_counts["matched"])
    total = 0
    seen_any = False
    for key in MATCHED_BUCKET_KEYS:
        v = bucket_counts.get(key)
        if isinstance(v, (int, float)):
            total += int(v)
            seen_any = True
    return total if seen_any else None


def build_key_counts(parity: Optional[Dict[str, Any]],
                     bucket_a_plan: Optional[Dict[str, Any]],
                     bucket_c_plan: Optional[Dict[str, Any]],
                     match_rate_pct: Optional[float]) -> Dict[str, Any]:
    """Distill the parity + remediation-plan JSONs into the small set of
    counts that drive the cutover decision. Anything absent comes back
    as None — never as zero — so the renderer can mark it 'unknown'."""
    p = parity or {}
    bucket_counts = p.get("bucket_counts") or {}
    if not isinstance(bucket_counts, dict):
        bucket_counts = {}
    square_count = p.get("square_count")
    hub_count = p.get("hub_count")
    matched = _derive_matched_count(bucket_counts)

    a = bucket_a_plan or {}
    a_actionable_cohorts = a.get("cohort_count_actionable")
    a_actionable_docs = a.get("actionable_doc_count")
    a_manual_review_cohorts = a.get("cohort_count_manual_review")
    a_change_type_counts = a.get("change_type_counts")

    c = bucket_c_plan or {}
    c_intake_cohorts = c.get("intake_channel_change_cohort_count")
    c_exclusion_cohorts = c.get("parity_exclusion_cohort_count")
    c_owner_counts = c.get("owner_hint_counts")

    projected_match_rate_pct = None
    projection_basis = None
    if (isinstance(square_count, (int, float)) and square_count > 0
            and isinstance(matched, (int, float))
            and isinstance(a_actionable_docs, (int, float))):
        projected_match_rate_pct = (
            (matched + a_actionable_docs) / square_count) * 100.0
        projection_basis = (
            f"(matched={int(matched)} + bucket_A_actionable_docs="
            f"{int(a_actionable_docs)}) / square_count={int(square_count)}"
        )

    return {
        "parity": {
            "square_count": square_count,
            "hub_count": hub_count,
            "matched_count": matched,
            "match_rate_pct": match_rate_pct,
            "bucket_counts": bucket_counts,
        },
        "bucket_A": {
            "actionable_cohort_count": a_actionable_cohorts,
            "actionable_doc_count": a_actionable_docs,
            "manual_review_cohort_count": a_manual_review_cohorts,
            "change_type_counts": a_change_type_counts,
        },
        "bucket_C": {
            "intake_channel_change_cohort_count": c_intake_cohorts,
            "parity_exclusion_cohort_count": c_exclusion_cohorts,
            "owner_hint_counts": c_owner_counts,
        },
        "projection": {
            "post_bucket_A_apply_match_rate_pct": projected_match_rate_pct,
            "basis": projection_basis,
        },
    }


# ---------------------------------------------------------------------------
# Pure decision engine
# ---------------------------------------------------------------------------

def classify_step(step: Dict[str, Any]) -> str:
    rc = int(step.get("rc", 0))
    if rc < 3 and step_log_has_traceback(step):
        rc = 3
    if rc >= 3:
        return "fail"
    if rc == 0:
        return "ok"
    return "ok_signal"  # rc 1/2 — completed with workflow signal


def step_log_has_traceback(step: Dict[str, Any]) -> bool:
    """Return True if the step's log file contains a Python traceback.
    Defense in depth: the bash orchestrator already escalates rc on
    traceback, but old proof dirs and any future orchestrator gap need
    to be caught here too."""
    log_path = step.get("log_path")
    if not log_path or not os.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Traceback (most recent call last):"):
                    return True
    except OSError:
        return False
    return False


def derive_blockers(manifest: Dict[str, Any],
                    match_rate_pct: Optional[float],
                    min_match_rate: float) -> List[str]:
    blockers: List[str] = []
    for s in manifest.get("steps", []):
        if classify_step(s) != "fail":
            continue
        suffix = ""
        if step_log_has_traceback(s):
            suffix = " [Python traceback in log]"
        blockers.append(
            f"step '{s.get('label', s.get('id', '?'))}' failed "
            f"(rc={s.get('rc')}){suffix}"
        )
    if match_rate_pct is None:
        blockers.append(
            "match_rate_pct unavailable (parity JSON missing or unparseable)"
        )
    elif match_rate_pct < min_match_rate:
        blockers.append(
            f"match_rate_pct={match_rate_pct:.2f} < required "
            f"{min_match_rate:.2f}"
        )
    return blockers


def build_summary(manifest: Dict[str, Any],
                  match_rate_pct: Optional[float],
                  min_match_rate: float,
                  parity_payload: Optional[Dict[str, Any]] = None,
                  bucket_a_plan: Optional[Dict[str, Any]] = None,
                  bucket_c_plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    steps = manifest.get("steps", [])
    statuses = [classify_step(s) for s in steps]
    blockers = derive_blockers(manifest, match_rate_pct, min_match_rate)
    decision = "GO" if not blockers else "NO-GO"
    key_counts = build_key_counts(parity_payload, bucket_a_plan,
                                  bucket_c_plan, match_rate_pct)
    return {
        "decision": decision,
        "blockers": blockers,
        "match_rate_pct": match_rate_pct,
        "min_match_rate_pct": min_match_rate,
        "step_count_total": len(steps),
        "step_count_ok": statuses.count("ok"),
        "step_count_ok_signal": statuses.count("ok_signal"),
        "step_count_fail": statuses.count("fail"),
        "key_counts": key_counts,
        "steps": [
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "rc": s.get("rc"),
                "status": classify_step(s),
                "log_path": s.get("log_path"),
                "duration_sec": s.get("duration_sec"),
            }
            for s in steps
        ],
        "proof_dir": manifest.get("proof_dir"),
        "started_at_utc": manifest.get("started_at_utc"),
        "finished_at_utc": manifest.get("finished_at_utc"),
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_markdown(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Square9 Cutover Readiness — Proof Pack Summary")
    lines.append("")
    lines.append(f"_Decision_: **{summary['decision']}**")
    lines.append("")
    lines.append(f"- Proof dir: `{summary.get('proof_dir')}`")
    lines.append(f"- Started UTC: {summary.get('started_at_utc')}")
    lines.append(f"- Finished UTC: {summary.get('finished_at_utc')}")
    rate = summary.get("match_rate_pct")
    rate_str = f"{rate:.2f}%" if isinstance(rate, (int, float)) else "unknown"
    lines.append(f"- match_rate_pct: **{rate_str}**  "
                 f"(min required: {summary['min_match_rate_pct']:.2f}%)")
    lines.append(f"- Steps: total={summary['step_count_total']} "
                 f"ok={summary['step_count_ok']} "
                 f"ok_signal={summary['step_count_ok_signal']} "
                 f"fail={summary['step_count_fail']}")
    lines.append("")
    kc = summary.get("key_counts") or {}
    parity = kc.get("parity") or {}
    a = kc.get("bucket_A") or {}
    c = kc.get("bucket_C") or {}
    proj = kc.get("projection") or {}
    lines.append("## Key counts")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("| --- | --- |")
    lines.append(f"| parity.square_count | {_fmt_int_or_unknown(parity.get('square_count'))} |")
    lines.append(f"| parity.hub_count | {_fmt_int_or_unknown(parity.get('hub_count'))} |")
    lines.append(f"| parity.matched_count | {_fmt_int_or_unknown(parity.get('matched_count'))} |")
    lines.append(f"| bucket_A.actionable_cohorts | {_fmt_int_or_unknown(a.get('actionable_cohort_count'))} |")
    lines.append(f"| bucket_A.actionable_docs | {_fmt_int_or_unknown(a.get('actionable_doc_count'))} |")
    lines.append(f"| bucket_A.manual_review_cohorts | {_fmt_int_or_unknown(a.get('manual_review_cohort_count'))} |")
    lines.append(f"| bucket_C.intake_channel_change_cohorts | {_fmt_int_or_unknown(c.get('intake_channel_change_cohort_count'))} |")
    lines.append(f"| bucket_C.parity_exclusion_cohorts | {_fmt_int_or_unknown(c.get('parity_exclusion_cohort_count'))} |")
    proj_rate = proj.get("post_bucket_A_apply_match_rate_pct")
    if proj_rate is not None:
        lines.append("")
        lines.append("### Projected match rate after Bucket A apply")
        lines.append("")
        lines.append(f"- **{_fmt_pct_or_unknown(proj_rate)}** "
                     f"(min required: {summary['min_match_rate_pct']:.2f}%)")
        lines.append(f"- Basis: {proj.get('basis')}")
        if proj_rate >= summary['min_match_rate_pct']:
            lines.append("- Bucket A apply alone should clear the GO gate.")
        else:
            lines.append("- Bucket A apply alone is **not** sufficient; "
                         "Bucket C intake-channel work also required.")
    lines.append("")
    if summary["blockers"]:
        lines.append("## Blockers")
        for b in summary["blockers"]:
            lines.append(f"- {b}")
        lines.append("")
    lines.append("## Steps")
    lines.append("")
    lines.append("| # | id | label | rc | status | duration_sec |")
    lines.append("| - | -- | ----- | -- | ------ | ------------ |")
    for i, s in enumerate(summary["steps"], 1):
        lines.append(
            f"| {i} | {s.get('id')} | {s.get('label')} | {s.get('rc')} | "
            f"{s.get('status')} | {s.get('duration_sec')} |"
        )
    lines.append("")
    lines.append("> READ-ONLY proof pack. No Mongo writes, no Exchange "
                 "changes, no Square9 cutover triggers.")
    lines.append("")
    return "\n".join(lines)


def _fmt_int_or_unknown(v: Any) -> str:
    if v is None:
        return "unknown"
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct_or_unknown(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:.2f}%"
    return "unknown"


def render_text(summary: Dict[str, Any]) -> str:
    rate = summary.get("match_rate_pct")
    rate_str = _fmt_pct_or_unknown(rate)
    out: List[str] = []
    out.append("=" * 66)
    out.append(f" Square9 Cutover Readiness — DECISION: {summary['decision']}")
    out.append("=" * 66)
    out.append(f"  proof_dir         : {summary.get('proof_dir')}")
    out.append(f"  started_at_utc    : {summary.get('started_at_utc')}")
    out.append(f"  finished_at_utc   : {summary.get('finished_at_utc')}")
    out.append(f"  match_rate_pct    : {rate_str}  "
               f"(min {summary['min_match_rate_pct']:.2f}%)")
    out.append(f"  steps             : total={summary['step_count_total']} "
               f"ok={summary['step_count_ok']} "
               f"ok_signal={summary['step_count_ok_signal']} "
               f"fail={summary['step_count_fail']}")
    out.append("")

    kc = summary.get("key_counts") or {}
    parity = kc.get("parity") or {}
    a = kc.get("bucket_A") or {}
    c = kc.get("bucket_C") or {}
    proj = kc.get("projection") or {}

    out.append("  KEY COUNTS:")
    out.append(f"    parity.square_count          : {_fmt_int_or_unknown(parity.get('square_count'))}")
    out.append(f"    parity.hub_count             : {_fmt_int_or_unknown(parity.get('hub_count'))}")
    out.append(f"    parity.matched_count         : {_fmt_int_or_unknown(parity.get('matched_count'))}")
    bcs = parity.get("bucket_counts") or {}
    if bcs:
        out.append(f"    parity.bucket_counts         :")
        for k, v in bcs.items():
            out.append(f"      {k:30s} {_fmt_int_or_unknown(v)}")
    out.append(f"    bucket_A.actionable_cohorts  : {_fmt_int_or_unknown(a.get('actionable_cohort_count'))}")
    out.append(f"    bucket_A.actionable_docs     : {_fmt_int_or_unknown(a.get('actionable_doc_count'))}")
    out.append(f"    bucket_A.manual_review_cohrts: {_fmt_int_or_unknown(a.get('manual_review_cohort_count'))}")
    ctc = a.get("change_type_counts")
    if ctc:
        out.append(f"    bucket_A.change_type_counts  :")
        for entry in ctc:
            try:
                k, v = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            out.append(f"      {str(k):30s} {_fmt_int_or_unknown(v)}")
    out.append(f"    bucket_C.intake_change_cohrts: {_fmt_int_or_unknown(c.get('intake_channel_change_cohort_count'))}")
    out.append(f"    bucket_C.exclusion_cohorts   : {_fmt_int_or_unknown(c.get('parity_exclusion_cohort_count'))}")

    proj_rate = proj.get("post_bucket_A_apply_match_rate_pct")
    if proj_rate is not None:
        out.append("")
        out.append("  PROJECTED MATCH RATE AFTER BUCKET A APPLY:")
        out.append(f"    {_fmt_pct_or_unknown(proj_rate)}  "
                   f"{proj.get('basis') or ''}")
        if proj_rate >= summary['min_match_rate_pct']:
            out.append(f"    >= {summary['min_match_rate_pct']:.2f}%   "
                       f"(Bucket A apply alone should clear the gate)")
        else:
            out.append(f"    <  {summary['min_match_rate_pct']:.2f}%   "
                       f"(Bucket A apply NOT sufficient; Bucket C "
                       f"intake-channel work also required)")
    out.append("")

    if summary["blockers"]:
        out.append("  BLOCKERS:")
        for b in summary["blockers"]:
            out.append(f"    - {b}")
    else:
        out.append("  blockers          : (none)")
    out.append("")
    out.append("  per-step rc / status:")
    for s in summary["steps"]:
        out.append(
            f"    rc={s.get('rc'):>3}  status={s.get('status'):10s}  "
            f"id={s.get('id'):40s}  label={s.get('label')}"
        )
    out.append("")
    out.append("  READ-ONLY proof pack. No production state was changed.")
    out.append("=" * 66)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Summarize a Square9 cutover proof pack (read-only).",
    )
    ap.add_argument("--proof-dir", required=True,
                    help="prod_reports/cutover_proof_<timestamp>/ dir")
    ap.add_argument("--manifest",
                    default=None,
                    help="Path to manifest.json (defaults to "
                         "<proof-dir>/manifest.json)")
    ap.add_argument("--min-match-rate", type=float,
                    default=DEFAULT_MIN_MATCH_RATE,
                    help="Minimum match_rate_pct required for GO "
                         "(default: 85.0)")
    args = ap.parse_args()

    manifest_path = args.manifest or os.path.join(
        args.proof_dir, "manifest.json")
    manifest = load_manifest(manifest_path)
    match_rate_pct = load_parity_match_rate(args.proof_dir)
    parity_payload = load_parity_payload(args.proof_dir)
    # Remediation-plan JSONs live under prod_reports/ (sibling of the
    # proof dir), not inside the proof dir itself, because the bucket
    # plan scripts have hardcoded default output paths. Resolve via the
    # proof_dir's parent.
    prod_reports_dir = os.path.dirname(os.path.normpath(args.proof_dir)) or "."
    bucket_a_plan = load_remediation_plan(
        os.path.join(prod_reports_dir, "bucket_A_remediation_plan.json"))
    bucket_c_plan = load_remediation_plan(
        os.path.join(prod_reports_dir, "bucket_C_remediation_plan.json"))

    summary = build_summary(manifest, match_rate_pct, args.min_match_rate,
                            parity_payload=parity_payload,
                            bucket_a_plan=bucket_a_plan,
                            bucket_c_plan=bucket_c_plan)

    summary_json = os.path.join(args.proof_dir, "summary.json")
    summary_md = os.path.join(args.proof_dir, "summary.md")
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write(render_markdown(summary))

    print(render_text(summary))
    print(f"  summary_json      : {summary_json}")
    print(f"  summary_md        : {summary_md}")
    return 0 if summary["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
