"""
bucket_A_wrapper_decision.py
============================
Read-only helper consumed by ``ops/run_bucket_A_apply_and_verify.sh``.

Reads the JSON written by ``bucket_A_apply_preflight.py --proof-dir <dir>``
(file name: ``BUCKET_A_APPLY_PREFLIGHT.json``) and emits a single
DECISION line plus a REASON line, so the bash wrapper can branch
without parsing nested JSON itself.

DECISION ∈ {apply, skip_apply, abort}

  apply      : at least one safe candidate exists and zero unsafe.
               Wrapper SHOULD run the gated apply step.
  skip_apply : every candidate is already_applied (idempotent
               success). Wrapper MUST skip the apply step and proceed
               to verify + proof pack.
  abort      : preflight is not actionable (unsafe candidates,
               zero candidates, or preflight exit code != 0). Wrapper
               MUST stop before any apply.

Exit codes:
  0  decision is ``apply`` or ``skip_apply``
  1  decision is ``abort``
  2  preflight JSON is missing or malformed
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Tuple


def decide(payload: Dict[str, Any]) -> Tuple[str, str]:
    """Pure, no I/O. Returns (decision, reason)."""
    rc = payload.get("exit_code")
    res = payload.get("result") or {}
    cand = int(res.get("candidate_count") or 0)
    safe = int(res.get("safe_count") or 0)
    already = int(res.get("already_applied_count") or 0)
    unsafe = int(res.get("unsafe_count") or 0)

    if rc != 0:
        return "abort", (
            f"preflight exit_code={rc} "
            f"(safe={safe} already_applied={already} unsafe={unsafe})"
        )
    if unsafe > 0:
        return "abort", f"{unsafe} unsafe candidate(s) present"
    if cand == 0:
        return "abort", "preflight reported zero candidates"
    if safe == 0 and already == cand:
        return "skip_apply", (
            f"all {cand} candidate(s) already in expected post-apply "
            f"state (already_applied_count={already})"
        )
    if safe > 0:
        return "apply", (
            f"{safe} safe candidate(s) ready for gated apply "
            f"(already_applied_count={already})"
        )
    return "abort", (
        f"safe_count=0 and already_applied_count={already}"
        f" != candidate_count={cand}"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: bucket_A_wrapper_decision.py <preflight_json_path>",
              file=sys.stderr)
        return 2
    path = sys.argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"DECISION=abort", flush=True)
        print(f"REASON=could not read preflight JSON at {path}: {e}",
              flush=True)
        return 2

    decision, reason = decide(payload)
    print(f"DECISION={decision}", flush=True)
    print(f"REASON={reason}", flush=True)
    return 0 if decision in ("apply", "skip_apply") else 1


if __name__ == "__main__":
    raise SystemExit(main())
