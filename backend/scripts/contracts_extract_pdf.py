"""Phase 4C(c) — One-shot PDF body extraction CLI.

Thin wrapper around ``services.contracts.pdf_extraction.run_extraction``
plus ``ContractIntelligenceService.ingest_pdf_extraction``. Sharing the
service guarantees the CLI and the HTTP endpoint can never drift.

**Default is dry-run.** Writes only happen with ``--commit``.

Usage (remote VM):

    # Dry-run (preview only, no DB writes):
    docker compose exec -w /app backend \\
        python -m scripts.contracts_extract_pdf <agreement_id> /tmp/agreement.pdf

    # Persist:
    docker compose exec -w /app backend \\
        python -m scripts.contracts_extract_pdf <agreement_id> /tmp/agreement.pdf --commit

Exit codes:
    0  — extraction completed (with or without ambiguities)
    2  — file could not be read or PDF unparsable
    3  — agreement_id not found in the contracts collection
    4  — invalid arguments / runtime error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import List, Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


from services.contracts.pdf_extraction import run_extraction  # noqa: E402
from services.contracts.contract_intelligence_service import (  # noqa: E402
    ContractIntelligenceService,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="contracts_extract_pdf",
        description=(
            "Run Phase 4C(c) PDF body extraction against an existing "
            "agreement. Dry-run is the default."
        ),
    )
    p.add_argument(
        "agreement_id",
        help="Existing agreement.id (UUID4) the PDF belongs to.",
    )
    p.add_argument("path", help="Path to a .pdf file on the VM.")
    p.add_argument(
        "--commit",
        action="store_true",
        help="Persist extracted fields. Omit for a safe dry-run preview.",
    )
    p.add_argument(
        "--actor",
        default="cli",
        help="Audit-log actor string. Defaults to 'cli'.",
    )
    return p


def _print_preview(preview: dict) -> None:
    print("=" * 80)
    print("PDF Extraction Preview")
    print(f"  agreement_id : {preview.get('agreement_id')}")
    print(f"  filename     : {preview.get('filename')}")
    print(f"  pages        : {preview.get('page_count')}")
    print(f"  bytes        : {preview.get('bytes_size')}")
    print(f"  text_chars   : {preview.get('text_chars')}")
    if preview.get("error"):
        print(f"  ERROR        : {preview['error']}")
    fields = preview.get("fields", []) or []
    line_pricing = preview.get("line_pricing", []) or []
    ambiguities = preview.get("ambiguities", []) or []
    print(f"  fields       : {len(fields)}")
    print(f"  line_pricing : {len(line_pricing)}")
    print(f"  ambiguities  : {len(ambiguities)}")
    print("-" * 80)
    for f in fields:
        print(f"  [{f['target']:>10}] {f['key']:<28} "
              f"conf={f['confidence']:.2f}  value={json.dumps(f['value'])}")
    if line_pricing:
        print("-" * 80)
        print("  Per-line MOQ overlays:")
        for lp in line_pricing:
            print(f"    item={lp['item_label']!r:<40} min_quantity={lp['min_quantity']} "
                  f"conf={lp['confidence']:.2f}")
    if ambiguities:
        print("-" * 80)
        print("  Ambiguities (would emit pdf_extraction_ambiguous exceptions):")
        for amb in ambiguities:
            print(f"    key={amb['key']!r}  candidates={len(amb['candidates'])}")
            for cand in amb["candidates"]:
                print(f"       conf={cand['confidence']:.2f}  value={json.dumps(cand['value'])}")
    print("-" * 80)


async def _run_async(
    *, agreement_id: str, path: str, commit: bool, actor: str,
) -> int:
    if not os.path.isfile(path):
        print(f"ERROR: {path!r} is not a file", file=sys.stderr)
        return 2
    with open(path, "rb") as fp:
        data = fp.read()
    if not data:
        print(f"ERROR: {path!r} is empty", file=sys.stderr)
        return 2

    result = run_extraction(
        agreement_id=agreement_id,
        data=data,
        filename=os.path.basename(path),
    )
    preview = result.to_dict()
    preview["mode"] = "commit" if commit else "dryrun"
    _print_preview(preview)

    if result.error and not commit:
        return 0  # dry-run still succeeds; caller sees ERROR line

    if not commit:
        print("(dry-run — no DB writes)")
        return 0

    try:
        from database import db  # noqa: WPS433  — lazy
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: cannot connect to database: {exc}", file=sys.stderr)
        return 4

    svc = ContractIntelligenceService(db)
    try:
        write_summary = await svc.ingest_pdf_extraction(
            agreement_id=agreement_id,
            result=result,
            actor=actor,
        )
    except LookupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: ingest_pdf_extraction failed: {exc}", file=sys.stderr)
        return 4

    print("Commit summary:")
    print(json.dumps(write_summary, indent=2, default=str))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run_async(
        agreement_id=args.agreement_id,
        path=args.path,
        commit=args.commit,
        actor=args.actor,
    ))


if __name__ == "__main__":
    sys.exit(main())
