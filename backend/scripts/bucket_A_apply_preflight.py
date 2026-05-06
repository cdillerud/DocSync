"""
bucket_A_apply_preflight.py
===========================
READ-ONLY preflight for the gated Bucket A one-shot data patch apply.

Runs the same cohort-and-row matching as
``bucket_A_one_shot_data_patch_apply.py``, then for each candidate doc
issues a single ``find_one`` against live ``hub_documents`` (read-only)
and validates a closed list of safety predicates BEFORE any apply step
is even discussed:

  S1  live doc_type            == "AP_INVOICE"
  S2  live suggested_job_type  in {"AP_Invoice", None, ""}  (compatible)
  S3  live mailbox_category    != "AP"   (would actually move)
  S4  doc appears in the Bucket A clean plan / cohort filter (by
      construction; never fails)
  S5  remediation_audit.source != "bucket_A_one_shot_patch"
      (idempotent; not already applied)

This script writes nothing to Mongo and triggers nothing else. It
prints:

  - dry-run exit code
  - candidate count   (= rows that matched a one_shot_data_patch cohort)
  - safe count        (= candidates that passed S1-S5)
  - unsafe count      (= candidates that failed any predicate)
  - exact doc IDs (safe + unsafe, with reasons)
  - exact ``update_one`` payloads that would be applied
  - the rollback file path the apply step WOULD create
  - projected post-apply match_rate_pct
  - the live apply command (NOT executed)
  - the rollback procedure (NOT executed)

Exit codes:
  0  preflight PASSED  (>= 1 safe candidate AND zero unsafe candidates)
  1  preflight FAILED  (>= 1 unsafe candidate)
  2  no candidates     (plan has no one_shot_data_patch rows that
                       match the live root-cause CSV)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Reuse the dry-run module for cohort/row matching, and the apply
# module for the canonical $set payload + idempotency marker.
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
from scripts import bucket_A_one_shot_data_patch_dryrun as ba_dryrun  # noqa: E402
from scripts import bucket_A_one_shot_data_patch_apply as ba_apply  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_DOC_TYPE = "AP_INVOICE"
COMPATIBLE_SUGGESTED_JOB_TYPES = {"AP_Invoice", "", None}
TARGET_MAILBOX_CATEGORY = "AP"

LIVE_APPLY_COMMAND = (
    "docker compose exec backend python "
    "scripts/bucket_A_one_shot_data_patch_apply.py --apply --confirm CUTOVER"
)


# ---------------------------------------------------------------------------
# Lazy live-collection accessor
# ---------------------------------------------------------------------------

def get_hub_documents_collection():
    """Same accessor as the apply script. Imported lazily so tests
    inject mongomock collections directly."""
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME env vars are required for the preflight.")
    client = MongoClient(mongo_url)
    return client[db_name]["hub_documents"]


# ---------------------------------------------------------------------------
# Safety predicates (pure)
# ---------------------------------------------------------------------------

def evaluate_safety(live_doc: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Apply S1-S5 to a single live doc. Returns (is_safe, reasons)."""
    reasons: List[str] = []
    if live_doc is None:
        return False, ["S0: doc not found in hub_documents"]
    if live_doc.get("doc_type") != REQUIRED_DOC_TYPE:
        reasons.append(
            f"S1: doc_type={live_doc.get('doc_type')!r} "
            f"(required AP_INVOICE)"
        )
    sjt = live_doc.get("suggested_job_type")
    if sjt not in COMPATIBLE_SUGGESTED_JOB_TYPES:
        reasons.append(
            f"S2: suggested_job_type={sjt!r} "
            f"(compatible: AP_Invoice / blank)"
        )
    if live_doc.get("mailbox_category") == TARGET_MAILBOX_CATEGORY:
        reasons.append(
            "S3: mailbox_category already 'AP' (apply would be a no-op)"
        )
    # S4 is structural — the candidate already came out of the cohort
    # filter — so we record it for transparency only.
    if ba_apply.is_already_applied(live_doc):
        reasons.append(
            "S5: remediation_audit.source already "
            "'bucket_A_one_shot_patch' (already applied)"
        )
    return (len(reasons) == 0), reasons


# ---------------------------------------------------------------------------
# Preflight core (collection injectable for tests)
# ---------------------------------------------------------------------------

def select_candidates(plan: Dict[str, Any],
                      rows: List[Dict[str, str]]
                      ) -> List[Tuple[str, Dict[str, Any], Dict[str, str]]]:
    """Return the (doc_id, cohort_key, source_row) triples that the
    apply step would target, in plan order. Pure / no I/O."""
    out: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []
    for c in ba_dryrun.select_one_shot_cohorts(plan):
        ck = c.get("cohort_key") or {}
        for r in rows:
            if not ba_dryrun.row_matches_cohort_key(r, ck):
                continue
            doc_id = (r.get("best_hub_doc_id") or "").strip()
            if doc_id:
                out.append((doc_id, ck, r))
    return out


def preflight(plan: Dict[str, Any],
              rows: List[Dict[str, str]],
              collection,
              parity_payload: Optional[Dict[str, Any]] = None,
              now: Optional[dt.datetime] = None,
              ) -> Dict[str, Any]:
    candidates = select_candidates(plan, rows)
    safe: List[Dict[str, Any]] = []
    unsafe: List[Dict[str, Any]] = []
    before_after_table: List[Dict[str, Any]] = []
    update_payloads: List[Dict[str, Any]] = []

    placeholder_applied_at = "<set at live apply time>"

    for doc_id, ck, row in candidates:
        live = collection.find_one({ba_apply.HUB_DOC_ID_FIELD: doc_id})
        is_safe, reasons = evaluate_safety(live)

        record = {
            "doc_id": doc_id,
            "cohort_key": dict(ck),
            "live_present": live is not None,
            "reasons": reasons,
        }
        if is_safe:
            safe.append({**record, "live_doc": live})
            update_payloads.append({
                "filter": {ba_apply.HUB_DOC_ID_FIELD: doc_id},
                "update": {
                    "$set": ba_apply.build_set_payload(
                        ck, placeholder_applied_at)
                },
            })
            before_after_table.append({
                "doc_id": doc_id,
                "file_name": (live or {}).get("file_name"),
                "email_sender": row.get("email_sender") or
                                (live or {}).get("email_sender"),
                "current_mailbox_category": (live or {}).get("mailbox_category"),
                "proposed_mailbox_category": "AP",
                "current_doc_type": (live or {}).get("doc_type"),
                "proposed_doc_type": "AP_INVOICE",
                "current_suggested_job_type": (live or {}).get("suggested_job_type"),
                "proposed_suggested_job_type": "AP_Invoice",
                "current_routing_status": (live or {}).get("routing_status"),
                "current_routing_reason": (live or {}).get("routing_reason"),
                "sharepoint_folder_path": (live or {}).get("sharepoint_folder_path"),
            })
        else:
            unsafe.append(record)

    rollback_dir = _predicted_rollback_dir(now)
    rollback_path = os.path.join(rollback_dir, "rollback.json")
    projected = _projected_match_rate(parity_payload, len(safe))

    return {
        "candidate_count": len(candidates),
        "safe_count": len(safe),
        "unsafe_count": len(unsafe),
        "safe": safe,
        "unsafe": unsafe,
        "before_after_table": before_after_table,
        "update_payloads": update_payloads,
        "predicted_rollback_path": rollback_path,
        "projected_match_rate_pct": projected,
        "live_apply_command": LIVE_APPLY_COMMAND,
    }


def _predicted_rollback_dir(now: Optional[dt.datetime]) -> str:
    ts = (now or dt.datetime.now(dt.timezone.utc)).strftime(
        "%Y-%m-%dT%H-%M-%SZ")
    return os.path.join("prod_reports", f"apply_bucket_A_{ts}")


def _projected_match_rate(parity: Optional[Dict[str, Any]],
                          safe_apply_count: int) -> Optional[float]:
    if not isinstance(parity, dict):
        return None
    sq = parity.get("square_count")
    bc = parity.get("bucket_counts") or {}
    matched: Optional[int] = None
    if isinstance(bc, dict):
        if isinstance(bc.get("matched"), (int, float)):
            matched = int(bc["matched"])
        else:
            total = 0
            seen = False
            for k in ("exact_match", "strong_evidence_match",
                      "likely_match", "possible_match"):
                v = bc.get(k)
                if isinstance(v, (int, float)):
                    total += int(v)
                    seen = True
            matched = total if seen else None
    if not isinstance(sq, (int, float)) or sq <= 0 or matched is None:
        return None
    return (matched + safe_apply_count) / sq * 100.0


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _exit_code(result: Dict[str, Any]) -> int:
    if result["candidate_count"] == 0:
        return 2
    if result["unsafe_count"] > 0:
        return 1
    if result["safe_count"] == 0:
        return 1
    return 0


ROLLBACK_PROCEDURE = """\
Rollback procedure (manual, executed only if a regression is observed):

  1. Locate the rollback file written by the apply step:
       prod_reports/apply_bucket_A_<UTC-ts>/rollback.json
  2. The file contains, per affected doc:
       - the prior values of mailbox_category, doc_type,
         suggested_job_type, remediation_audit
       - or markers __missing_<field>: true for any field that did not
         exist before the apply
  3. To restore: iterate rollback_records and for each record issue an
     update_one({_id: <id>}, ...) that:
       - $sets each prior field value, AND
       - $unsets any field marked __missing_<field>
  4. Re-run the proof pack to confirm the match rate has returned to its
     pre-apply value.
  5. No rollback runner script ships in this repo today; ask for one if
     a rollback is anticipated.
"""


def render_text(result: Dict[str, Any], rc: int) -> str:
    out: List[str] = []
    out.append("=" * 72)
    out.append(f" Bucket A apply preflight — {'PASS' if rc == 0 else 'FAIL'} "
               f"(exit code {rc})")
    out.append("=" * 72)
    out.append(f"  candidate_count  : {result['candidate_count']}")
    out.append(f"  safe_count       : {result['safe_count']}")
    out.append(f"  unsafe_count     : {result['unsafe_count']}")
    proj = result.get("projected_match_rate_pct")
    if isinstance(proj, (int, float)):
        out.append(f"  projected match  : {proj:.2f}%   "
                   f"(after {result['safe_count']} safe apply(s))")
    else:
        out.append("  projected match  : unknown "
                   "(parity payload unavailable)")
    out.append(f"  rollback_path    : {result['predicted_rollback_path']}")
    out.append("")

    if result["safe"]:
        out.append(f"  SAFE DOC IDS ({len(result['safe'])}):")
        for s in result["safe"]:
            out.append(f"    {s['doc_id']}")
        out.append("")

    if result["unsafe"]:
        out.append(f"  UNSAFE DOC IDS ({len(result['unsafe'])}):")
        for u in result["unsafe"]:
            out.append(f"    {u['doc_id']}")
            for r in u["reasons"]:
                out.append(f"      - {r}")
        out.append("")

    if result["before_after_table"]:
        out.append("  BEFORE / AFTER (safe candidates only):")
        out.append(f"    {'doc_id':36s}  "
                   f"{'sender':30s}  "
                   f"cur_cat -> AP   "
                   f"cur_type -> AP_INVOICE   "
                   f"cur_sjt -> AP_Invoice")
        for r in result["before_after_table"]:
            out.append(
                f"    {(r['doc_id'] or ''):36s}  "
                f"{(r['email_sender'] or '')[:30]:30s}  "
                f"{(r['current_mailbox_category'] or '<none>'):8s}-> AP   "
                f"{(r['current_doc_type'] or '<none>'):10s}-> AP_INVOICE   "
                f"{(r['current_suggested_job_type'] or '<none>'):10s}"
                f"-> AP_Invoice"
            )
        out.append("")
        out.append("  full per-doc rows (file_name, routing_status, "
                   "routing_reason, sharepoint_folder_path) are in the "
                   "JSON output.")
        out.append("")

    if result["update_payloads"]:
        out.append(f"  UPDATE_ONE PAYLOADS ({len(result['update_payloads'])}):")
        for p in result["update_payloads"]:
            out.append(
                "    db.hub_documents.update_one("
                f"{json.dumps(p['filter'], default=str)}, "
                f"{json.dumps(p['update'], default=str)})"
            )
        out.append("")

    out.append("  LIVE APPLY COMMAND (not executed by this preflight):")
    out.append(f"    {result['live_apply_command']}")
    out.append("")
    out.append(ROLLBACK_PROCEDURE)
    out.append("")
    out.append("  READ-ONLY preflight: no DB writes, no cutover, "
               "no Square9 archive.")
    out.append("=" * 72)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only preflight for the gated Bucket A apply.",
    )
    p.add_argument("--plan-json",
                   default="prod_reports/bucket_A_remediation_plan.json")
    p.add_argument("--root-cause-csv",
                   default="prod_reports/bucket_A_root_cause.csv")
    p.add_argument("--parity-json",
                   default="prod_reports/square9_hub_ap_parity.json",
                   help="For projected match-rate calculation. Optional; "
                        "the projection prints 'unknown' if absent.")
    p.add_argument("--proof-dir", default=None,
                   help="If supplied, writes preflight.json into this "
                        "proof dir alongside the printed banner.")
    args = p.parse_args()

    plan = ba_dryrun.load_plan(args.plan_json)
    rows = ba_dryrun.load_rows(args.root_cause_csv)
    parity_payload: Optional[Dict[str, Any]] = None
    if os.path.exists(args.parity_json):
        try:
            with open(args.parity_json, "r", encoding="utf-8") as f:
                parity_payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            parity_payload = None
    if not isinstance(parity_payload, dict):
        # Fall back: scan raw text for the JSON blob (parity log preamble).
        try:
            with open(args.parity_json, "r", encoding="utf-8") as f:
                txt = f.read()
            for i, line in enumerate(txt.splitlines()):
                if line.lstrip().startswith("{"):
                    payload = json.loads("\n".join(txt.splitlines()[i:]))
                    if isinstance(payload, dict):
                        parity_payload = payload
                    break
        except (OSError, json.JSONDecodeError):
            pass

    coll = get_hub_documents_collection()
    result = preflight(plan, rows, coll, parity_payload=parity_payload)
    rc = _exit_code(result)

    print(render_text(result, rc))

    if args.proof_dir:
        os.makedirs(args.proof_dir, exist_ok=True)
        out_path = os.path.join(args.proof_dir, "BUCKET_A_APPLY_PREFLIGHT.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "exit_code": rc,
                "result": _strip_for_json(result),
            }, f, default=str, indent=2)
        print(f"  preflight_json   : {out_path}")

    return rc


def _strip_for_json(result: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the live_doc payloads (potentially huge) before persisting."""
    out = dict(result)
    out["safe"] = [{k: v for k, v in s.items() if k != "live_doc"}
                   for s in result.get("safe", [])]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
