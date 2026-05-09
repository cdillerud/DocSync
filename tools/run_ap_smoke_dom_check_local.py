"""
run_ap_smoke_dom_check_local.py
===============================
Convenience wrapper around ``backend/scripts/ap_smoke_walk_dom_check.py``
that lets you run the automated AP smoke DOM check from the SAME
machine where you captured login state with
``tools/capture_hub_storage_state.py`` — avoiding any need to copy
``hub_storage_state.json`` to a remote VM.

Strict scope:
    - Read-only.
    - No backend changes.
    - No Mongo / data writes.
    - No Save / Mark Ready / Post.
    - Just dispatches to the existing DOM check script with the
      authenticated storage state, then echoes the output paths.

Inputs (all paths can be absolute or relative to CWD):
    --smoke-csv          path to AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv
    --hub-origin         Hub URL (e.g. http://4.204.41.190:8080)
    --storage-state-path JSON produced by capture_hub_storage_state.py
    --out-dir            where to drop CSV / MD / screenshots
    --priorities         e.g. "P0,P1" (default: P0,P1)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional


DEFAULT_PRIORITIES = "P0,P1"
DEFAULT_OUT_DIR = "prod_reports"
DEFAULT_DOM_CHECK_SCRIPT = os.path.join(
    "backend", "scripts", "ap_smoke_walk_dom_check.py")


def _resolve_dom_check_script(explicit: Optional[str]) -> str:
    """Locate ap_smoke_walk_dom_check.py relative to repo layout.

    Order: explicit CLI arg → repo-relative default → /app default.
    """
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    candidates.append(DEFAULT_DOM_CHECK_SCRIPT)
    candidates.append(os.path.join(
        os.path.dirname(__file__), "..", DEFAULT_DOM_CHECK_SCRIPT))
    candidates.append("/app/backend/scripts/ap_smoke_walk_dom_check.py")
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    raise FileNotFoundError(
        "Could not locate ap_smoke_walk_dom_check.py. Pass "
        "--dom-check-script explicitly.")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Local runner for the AP smoke DOM check.")
    p.add_argument("--hub-origin", required=True,
                   help="e.g. http://4.204.41.190:8080")
    p.add_argument("--storage-state-path", required=True,
                   help="Path to hub_storage_state.json from "
                        "capture_hub_storage_state.py.")
    p.add_argument("--smoke-csv",
                   default="prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--priorities", default=DEFAULT_PRIORITIES)
    p.add_argument("--timeout-ms", type=int, default=20000)
    p.add_argument("--dom-check-script", default="",
                   help="Override path to ap_smoke_walk_dom_check.py.")
    args = p.parse_args(argv)

    if not os.path.exists(args.storage_state_path):
        sys.stderr.write(
            "run_ap_smoke_dom_check_local: --storage-state-path "
            f"missing: {args.storage_state_path!r}. Run "
            "tools/capture_hub_storage_state.py first.\n")
        return 2
    if not os.path.exists(args.smoke_csv):
        sys.stderr.write(
            "run_ap_smoke_dom_check_local: --smoke-csv missing: "
            f"{args.smoke_csv!r}.\n")
        return 2

    try:
        dom_script = _resolve_dom_check_script(args.dom_check_script or None)
    except FileNotFoundError as e:
        sys.stderr.write(f"run_ap_smoke_dom_check_local: {e}\n")
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    out_csv = os.path.join(args.out_dir,
                           "AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv")
    out_md = os.path.join(args.out_dir,
                          "AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md")
    shots = os.path.join(args.out_dir, "ap_smoke_walk_screens")

    cmd = [
        sys.executable, dom_script,
        "--hub-origin", args.hub_origin,
        "--priorities", args.priorities,
        "--input-csv", args.smoke_csv,
        "--out-csv", out_csv,
        "--out-summary-md", out_md,
        "--screenshot-dir", shots,
        "--headed", "false",
        "--timeout-ms", str(args.timeout_ms),
        "--storage-state-path", args.storage_state_path,
    ]

    print("=" * 72)
    print(" run_ap_smoke_dom_check_local")
    print("=" * 72)
    print("  invoking:")
    print("    " + " ".join(cmd))
    print()

    rc = subprocess.call(cmd)

    print()
    print("=" * 72)
    print(f"  exit code        : {rc}")
    print(f"  out_csv          : {out_csv}")
    print(f"  out_summary_md   : {out_md}")
    print(f"  screenshots      : {shots}/")
    print("  READ-ONLY. No clicks, no DB writes.")
    print("=" * 72)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
