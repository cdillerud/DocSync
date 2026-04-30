"""Phase 4B/4C — One-shot DocuSign Navigator → Contract Intelligence import CLI.

Thin wrapper around ``services.contracts.navigator_import``. The HTTP
endpoint at ``POST /api/contracts/navigator/import`` shares the exact
same service, so the two ingest paths cannot drift.

**Default is dry-run.** Writes only happen with ``--commit``.

Usage (remote VM):

    # Dry-run on Charlie's xlsx:
    docker compose exec -w /app backend \\
        python -m scripts.contracts_import_navigator /tmp/navigator.xlsx

    # Persist:
    docker compose exec -w /app backend \\
        python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --commit

Exit codes:
    0  — every row processed cleanly (includes "skipped as duplicate")
    2  — file could not be read or its shape is unsupported
    3  — one or more rows failed normalization or commit
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import List, Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


from services.contracts.navigator_import import (  # noqa: E402
    ImportSummary,
    NavigatorImportError,
    RowReport,
    commit_rows,
    dryrun_rows,
    parse_upload,
)


# ---------------------------------------------------------------------------
# Backwards-compat re-exports — older tests imported helpers from this
# module before the shared service existed. Keep them working.
# ---------------------------------------------------------------------------

def load_rows(path: str, *, sheet: Optional[str]):
    """Read a Navigator file from disk and return its rows."""
    with open(path, "rb") as fp:
        data = fp.read()
    filename = os.path.basename(path)
    return parse_upload(data=data, filename=filename, sheet=sheet)


def dryrun_row(index: int, row):
    """Synchronous one-row dry-run helper retained for tests / callers."""
    from services.contracts.navigator_import import dryrun_one as _dryrun
    report = _dryrun(index, row)
    # Adapt to the legacy CLI report shape (carries the full
    # NormalizedAgreement so the printer can read its tabs). We still
    # expose the same public attributes the previous CLI did.
    return _LegacyReportAdapter(report, row)


async def commit_row(svc, index: int, row):
    """Async one-row commit helper retained for tests."""
    from services.contracts.navigator_import import commit_one as _commit
    report = await _commit(svc, index, row)
    return _LegacyReportAdapter(report, row)


class _LegacyReportAdapter:
    """Map :class:`RowReport` to the old CLI report attribute surface
    (``party_count()``, ``term_count()`` callables) so the previous CLI
    tests keep passing without alteration."""

    def __init__(self, report: RowReport, row):
        self._report = report
        self._row = row

    # Public attributes pass-through.
    @property
    def index(self): return self._report.index
    @property
    def envelope_id(self): return self._report.envelope_id
    @property
    def provider_agreement_id(self): return self._report.provider_agreement_id
    @property
    def title(self): return self._report.title
    @property
    def status(self): return self._report.status
    @property
    def error(self): return self._report.error
    @property
    def committed(self): return self._report.committed
    @property
    def duplicate(self): return self._report.duplicate
    @property
    def agreement_id(self): return self._report.agreement_id
    @property
    def link_count(self): return self._report.link_count
    @property
    def exception_count(self): return self._report.exception_count
    @property
    def normalized(self):
        # Re-normalize on demand for the printer (kept lazy so failed
        # rows don't try to render).
        if self._report.error:
            return None
        from services.contracts.navigator_normalizer import normalize_navigator_row
        return normalize_navigator_row(self._row)

    def party_count(self): return self._report.party_count
    def term_count(self): return self._report.term_count
    def pricing_count(self): return self._report.pricing_count
    def document_count(self): return self._report.document_count
    def warning_count(self): return self._report.warning_count


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _print_header(mode: str, path: str, row_count: int) -> None:
    print("=" * 80)
    print(f"Navigator import — mode: {mode}")
    print(f"  source:       {path}")
    print(f"  total rows:   {row_count}")
    print("=" * 80)


def _print_row(report: RowReport, *, mode: str) -> None:
    banner = f"[{report.index:>4}]"
    if report.error:
        print(f"{banner} ERROR: {report.error}")
        return
    env_id = report.envelope_id or "?"
    title = (report.title or "")[:60]
    status = report.status or "?"
    print(
        f"{banner} envelope={env_id}  status={status}  "
        f"title={title!r}"
    )
    print(
        f"       nav_uuid={report.provider_agreement_id or '-'}  "
        f"parties={report.party_count}  "
        f"terms={report.term_count}  "
        f"pricing={report.pricing_count}  "
        f"docs={report.document_count}  "
        f"warnings={report.warning_count}"
    )
    if mode == "commit":
        if report.duplicate:
            print("       -> skipped (duplicate event id; already imported)")
        elif report.committed:
            print(
                f"       -> committed agreement_id={report.agreement_id} "
                f"links={report.link_count} exceptions={report.exception_count}"
                + (" [AMBIGUOUS]" if report.has_ambiguity_exception else "")
            )
        else:
            print("       -> NOT committed")
    if report.warning_count:
        for w in report.warnings:
            print(f"         . warn: {w.get('code')} {w.get('details')}")


def _print_summary(summary: ImportSummary) -> None:
    print("-" * 80)
    print("Summary")
    print(f"  rows processed:   {summary.row_count}")
    print(f"  normalizer errors:{summary.error_count}")
    print(f"  total warnings:   {summary.warning_count}")
    print(f"  schema gaps:      {summary.schema_gap_warnings}")
    print(f"  parties detected: {summary.parties_detected}")
    print(f"  terms detected:   {summary.terms_detected}")
    print(f"  pricing rows:     {summary.pricing_detected}")
    print(f"  documents:        {summary.documents_detected}")
    if summary.mode == "commit":
        print(f"  committed:        {summary.committed}")
        print(f"  skipped (dup):    {summary.skipped}")
        print(f"  ambiguity excs:   {summary.ambiguity_exceptions}")
    else:
        print(f"  would create:     {summary.would_create}")
        print(f"  would update:     {summary.would_update}")
        print("  (dry-run — no DB writes)")
    print("-" * 80)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="contracts_import_navigator",
        description=(
            "Import or dry-run a DocuSign Navigator AI Metadata Export into "
            "the Contract Intelligence store. Dry-run is the default."
        ),
    )
    p.add_argument(
        "path",
        help="Path to the Navigator .xlsx / .csv / .json file on the VM.",
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Actually persist rows. Omit for a safe dry-run.",
    )
    p.add_argument(
        "--sheet",
        default=None,
        help="Worksheet name (xlsx only). Defaults to the active sheet.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N rows (debugging).",
    )
    return p


async def _run_async(rows, *, commit: bool, filename: str) -> ImportSummary:
    if commit:
        from database import db  # noqa: WPS433  (intentional lazy import)
        return await commit_rows(rows, db=db, filename=filename)
    # Dry-run: try to use db so would_create / would_update are accurate,
    # but fall back to no-db mode if the import surface raises (e.g.
    # running pure unit tests against a fixture without Mongo).
    try:
        from database import db  # noqa: WPS433
        return await dryrun_rows(rows, db=db, filename=filename)
    except Exception:  # noqa: BLE001
        return await dryrun_rows(rows, db=None, filename=filename)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = load_rows(args.path, sheet=args.sheet)
    except (FileNotFoundError, PermissionError, NavigatorImportError) as exc:
        print(f"ERROR: cannot read {args.path!r}: {exc}", file=sys.stderr)
        return 2

    if args.limit is not None and args.limit >= 0:
        rows = rows[: args.limit]
    if not rows:
        print(f"ERROR: no rows found in {args.path!r}", file=sys.stderr)
        return 2

    mode = "commit" if args.commit else "dryrun"
    _print_header("commit" if args.commit else "dry-run", args.path, len(rows))

    summary = asyncio.run(
        _run_async(
            rows,
            commit=args.commit,
            filename=os.path.basename(args.path),
        )
    )

    for r in summary.rows:
        _print_row(r, mode=mode)
    _print_summary(summary)

    if summary.error_count:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
