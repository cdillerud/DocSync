"""
Tier 1 Post-Batch Report Generator (read-only).

Reads /app/memory/TIER1_BATCH_RESULTS.md, the most recent batch table, and
emits an operator-readable rollup:
  - bucket counts
  - top failure category
  - per-category top remediation hint
  - whether the batch crossed the Tier 1 viability bar (≥7/10 P1+P2; 0 F-BUG)

Usage:
  python /app/backend/scripts/tier1_post_batch_report.py
  python /app/backend/scripts/tier1_post_batch_report.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

WORKSHEET = Path("/app/memory/TIER1_BATCH_RESULTS.md")

REMEDIATION = {
    "F-CONFIG":  "Re-check BC_WRITE_ENVIRONMENT / BC_BLOCK_PRODUCTION_WRITES / BC_WRITE_ENABLED env values.",
    "F-AUTH":    "BC OAuth credential or scope problem — refresh BC_CLIENT_SECRET, validate tenant ID.",
    "F-REF":     "Reference-data gap — vendor not in BC, missing GL account, location code, or currency.",
    "F-DATA":    "Extraction missing/wrong — invoice_number, invoice_date, total, or no line items.",
    "F-DUP":     "By design: BC already has this PI; classifier correctly refused. Not a regression.",
    "F-RULE":    "BC posting rule rejected — closed period, vendor on hold, document date out of range.",
    "F-NETWORK": "Transient — retry. If recurs, check BC API rate limits or VM egress.",
    "F-BUG":     "Hub bug — see detail; do not run another batch until fixed.",
}


def _parse_latest_batch(text: str) -> List[Dict[str, str]]:
    sections = re.split(r"\n## Batch run @ ", text)
    if len(sections) < 2:
        return []
    last = sections[-1]
    rows: List[Dict[str, str]] = []
    for line in last.splitlines():
        if not line.startswith("| ") or line.startswith("| #") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 11:
            continue
        rows.append({
            "n": cells[0],
            "doc_id": cells[1].strip("`"),
            "vendor": cells[2],
            "invoice_no": cells[3],
            "total": cells[4],
            "dup": cells[5],
            "bucket": cells[6].replace("**", ""),
            "bc_invoice_no": cells[7],
            "http": cells[8],
            "elapsed_ms": cells[9],
            "detail": cells[10],
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = p.parse_args()

    if not WORKSHEET.exists():
        print(f"No worksheet at {WORKSHEET}; run tier1_batch_runner.py first.")
        return 2
    rows = _parse_latest_batch(WORKSHEET.read_text())
    if not rows:
        print(f"No batch rows found in {WORKSHEET}.")
        return 2

    counts = Counter(r["bucket"] for r in rows)
    pass_count = counts.get("P1", 0) + counts.get("P2", 0)
    bug_count = counts.get("F-BUG", 0)
    viable = (pass_count >= 7) and (bug_count == 0) and (len(rows) >= 10)

    if args.json:
        print(json.dumps({
            "rows_total": len(rows),
            "bucket_counts": dict(counts),
            "pass_count": pass_count,
            "bug_count": bug_count,
            "viable": viable,
            "rows": rows,
        }, indent=2))
        return 0

    print("=" * 72)
    print("Tier 1 Batch Report — most recent run")
    print("=" * 72)
    print(f"  rows: {len(rows)}")
    for bucket in ("P1", "P2", "F-DUP", "F-CONFIG", "F-AUTH", "F-REF", "F-DATA", "F-RULE", "F-NETWORK", "F-BUG"):
        if counts.get(bucket):
            print(f"    {bucket:10s} {counts[bucket]:>3}    — {REMEDIATION[bucket]}")
    print()
    print(f"  PASS={pass_count}/10  F-BUG={bug_count}")
    print(f"  RESULT: {'✅ TIER 1 VIABLE' if viable else '❌ NOT YET'}")
    if not viable:
        # Highest-frequency non-pass bucket = first remediation target
        non_pass = [(b, n) for b, n in counts.items() if b not in ("P1", "P2", "F-DUP")]
        if non_pass:
            top = sorted(non_pass, key=lambda x: -x[1])[0]
            print(f"  Highest-priority remediation: {top[0]} ({top[1]} doc(s)) — {REMEDIATION[top[0]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
