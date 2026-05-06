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
    no parity JSON is present or it lacks the field."""
    candidates = [
        os.path.join(proof_dir, "square9_hub_ap_parity.json"),
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.json"),
        # The orchestrator runs the parity script with `--json`, which
        # prints a JSON blob to stdout. The orchestrator captures stdout
        # into the per-step log file, so the .log itself is valid JSON.
        os.path.join(proof_dir, "logs", "square9_hub_ap_parity_report.log"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        rate = _extract_match_rate(payload)
        if rate is not None:
            return rate
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
# Pure decision engine
# ---------------------------------------------------------------------------

def classify_step(step: Dict[str, Any]) -> str:
    rc = int(step.get("rc", 0))
    if rc >= 3:
        return "fail"
    if rc == 0:
        return "ok"
    return "ok_signal"  # rc 1/2 — completed with workflow signal


def derive_blockers(manifest: Dict[str, Any],
                    match_rate_pct: Optional[float],
                    min_match_rate: float) -> List[str]:
    blockers: List[str] = []
    failed = [s for s in manifest.get("steps", [])
              if classify_step(s) == "fail"]
    for s in failed:
        blockers.append(
            f"step '{s.get('label', s.get('id', '?'))}' failed "
            f"(rc={s.get('rc')})"
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
                  min_match_rate: float) -> Dict[str, Any]:
    steps = manifest.get("steps", [])
    statuses = [classify_step(s) for s in steps]
    blockers = derive_blockers(manifest, match_rate_pct, min_match_rate)
    decision = "GO" if not blockers else "NO-GO"
    return {
        "decision": decision,
        "blockers": blockers,
        "match_rate_pct": match_rate_pct,
        "min_match_rate_pct": min_match_rate,
        "step_count_total": len(steps),
        "step_count_ok": statuses.count("ok"),
        "step_count_ok_signal": statuses.count("ok_signal"),
        "step_count_fail": statuses.count("fail"),
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


def render_text(summary: Dict[str, Any]) -> str:
    rate = summary.get("match_rate_pct")
    rate_str = f"{rate:.2f}%" if isinstance(rate, (int, float)) else "unknown"
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

    summary = build_summary(manifest, match_rate_pct, args.min_match_rate)

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
