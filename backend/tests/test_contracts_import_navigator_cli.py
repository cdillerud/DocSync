"""Phase 4B — DocuSign Navigator import CLI tests.

Exercises the one-shot CLI at ``scripts/contracts_import_navigator.py``
end-to-end without talking to Mongo. Commit-mode coverage uses an
in-memory fake orchestrator so idempotent-rerun behavior is tested
without requiring a live DB in the unit-test container.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import contracts_import_navigator as cli

BRAGG_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "docusign"
    / "bragg"
    / "bragg_metadata_export_redacted.json"
)


def _bragg_row() -> Dict[str, Any]:
    return json.loads(BRAGG_FIXTURE.read_text(encoding="utf-8"))["row"]


# =============================================================================
# Loaders
# =============================================================================

class TestLoaders:

    def test_loads_json_fixture_with_row_wrapper(self):
        rows = cli.load_rows(str(BRAGG_FIXTURE), sheet=None)
        assert len(rows) == 1
        assert rows[0]["Envelope Id"] == "3a85f196-5f70-830b-82c2-1bec243dab9e"

    def test_loads_naked_list_json(self, tmp_path: Path):
        path = tmp_path / "rows.json"
        path.write_text(json.dumps([_bragg_row(), _bragg_row()]))
        rows = cli.load_rows(str(path), sheet=None)
        assert len(rows) == 2

    def test_loads_rows_key_json(self, tmp_path: Path):
        path = tmp_path / "rows.json"
        path.write_text(json.dumps({"rows": [_bragg_row()]}))
        rows = cli.load_rows(str(path), sheet=None)
        assert len(rows) == 1

    def test_loads_csv_with_header(self, tmp_path: Path):
        row = _bragg_row()
        path = tmp_path / "nav.csv"
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
        rows = cli.load_rows(str(path), sheet=None)
        assert len(rows) == 1
        assert rows[0]["Envelope Id"] == row["Envelope Id"]

    def test_loads_xlsx(self, tmp_path: Path):
        openpyxl = pytest.importorskip("openpyxl")
        row = _bragg_row()
        path = tmp_path / "nav.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(list(row.keys()))
        ws.append(list(row.values()))
        wb.save(str(path))
        rows = cli.load_rows(str(path), sheet=None)
        assert len(rows) == 1
        assert rows[0]["Envelope Id"] == row["Envelope Id"]

    def test_rejects_unknown_extension(self, tmp_path: Path):
        path = tmp_path / "nav.txt"
        path.write_text("not a navigator export")
        with pytest.raises(ValueError, match="unsupported"):
            cli.load_rows(str(path), sheet=None)


# =============================================================================
# Dry-run
# =============================================================================

class TestDryRun:

    def test_dryrun_produces_report_per_row(self):
        report = cli.dryrun_row(1, _bragg_row())
        assert report.error is None
        assert report.envelope_id == "3a85f196-5f70-830b-82c2-1bec243dab9e"
        assert report.provider_agreement_id == "0bebdb15-3f95-4d95-9ad1-6282da1587a5"
        assert report.status == "completed"
        assert report.party_count() == 2
        # Every Navigator term key we expect after Phase 4A.
        terms = {t.term_key for t in report.normalized.terms}
        assert "agreement_type" in terms
        assert "payment_term" in terms

    def test_dryrun_captures_error_without_raising(self):
        # Missing Envelope Id must not raise — it must surface as error.
        report = cli.dryrun_row(7, {"Agreement Type": "MSA", "Parties": "A;B"})
        assert report.error is not None
        assert "Envelope Id" in report.error
        assert report.normalized is None

    def test_main_dryrun_exits_zero_on_clean_run(self, capsys):
        rc = cli.main([str(BRAGG_FIXTURE)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "mode: dry-run" in out
        assert "envelope=3a85f196" in out
        assert "dry-run — no DB writes" in out

    def test_main_honors_limit(self, tmp_path: Path, capsys):
        row = _bragg_row()
        path = tmp_path / "multi.json"
        path.write_text(json.dumps([row, row, row]))
        rc = cli.main([str(path), "--limit", "2"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "total rows:   2" in out

    def test_main_returns_nonzero_when_file_missing(self, capsys):
        rc = cli.main(["/nonexistent/nav.csv"])
        assert rc == 2

    def test_main_returns_nonzero_on_row_errors(self, tmp_path: Path):
        # One good row + one bad row → exit code 3.
        bad_row = {"Agreement Type": "MSA"}  # missing Envelope Id
        path = tmp_path / "mixed.json"
        path.write_text(json.dumps([_bragg_row(), bad_row]))
        rc = cli.main([str(path)])
        assert rc == 3


# =============================================================================
# Commit path — uses a fake orchestrator to exercise idempotency behavior
# =============================================================================

class _FakeOrchestrator:
    """Pretends to be :class:`ContractIntelligenceService`. Implements only
    ``record_event`` + ``process_event`` with the same contract the CLI
    depends on — and tracks calls for assertions.
    """

    def __init__(self) -> None:
        self.recorded: List[Dict[str, Any]] = []
        self.processed: List[str] = []
        # provider_event_id → event_id for fast dedupe check.
        self._event_index: Dict[str, str] = {}
        self._counter = 0

    async def record_event(self, **kw: Any) -> Dict[str, Any]:
        self.recorded.append(kw)
        provider_event_id = kw["provider_event_id"]
        if provider_event_id in self._event_index:
            return {
                "duplicate": True,
                "event_id": self._event_index[provider_event_id],
            }
        self._counter += 1
        eid = f"evt-{self._counter}"
        self._event_index[provider_event_id] = eid
        return {"duplicate": False, "event_id": eid}

    async def process_event(self, event_id: str) -> Dict[str, Any]:
        self.processed.append(event_id)
        return {
            "status": "ok",
            "event_id": event_id,
            "agreement_id": f"agr-{event_id}",
            "links": 2,
            "exceptions": 1,
            "warnings": 0,
        }


class TestCommitMode:

    @pytest.mark.asyncio
    async def test_commit_first_pass_records_and_processes(self):
        fake = _FakeOrchestrator()
        report = await cli.commit_row(fake, 1, _bragg_row())
        assert report.committed is True
        assert report.duplicate is False
        assert report.agreement_id == "agr-evt-1"
        assert report.link_count == 2
        assert report.exception_count == 1
        # record_event was called with a deterministic navigator event id.
        assert fake.recorded[0]["provider_event_id"] == (
            "navigator::3a85f196-5f70-830b-82c2-1bec243dab9e"
        )
        assert fake.recorded[0]["transport"] == "manual"

    @pytest.mark.asyncio
    async def test_commit_second_pass_is_idempotent_no_op(self):
        fake = _FakeOrchestrator()
        await cli.commit_row(fake, 1, _bragg_row())
        second = await cli.commit_row(fake, 1, _bragg_row())
        # Only ONE process_event invocation across both passes (replay skipped).
        assert len(fake.processed) == 1
        assert second.duplicate is True
        assert second.committed is False
        assert second.agreement_id is None

    @pytest.mark.asyncio
    async def test_commit_skips_rows_that_fail_normalization(self):
        fake = _FakeOrchestrator()
        report = await cli.commit_row(fake, 9, {"Agreement Type": "MSA"})
        assert report.error is not None
        assert report.committed is False
        # No orchestrator traffic for rows that failed pre-commit.
        assert fake.recorded == []
        assert fake.processed == []

    @pytest.mark.asyncio
    async def test_commit_path_reuses_navigator_event_id_per_envelope(self):
        """Even if the row dict is mutated between passes, the deterministic
        event id keeps replay idempotent."""
        fake = _FakeOrchestrator()
        row = _bragg_row()
        await cli.commit_row(fake, 1, row)
        # Change a cosmetic field; envelope id is the same so the event id
        # stays ``navigator::<envelope_id>``.
        row["Summary"] = "changed between passes"
        second = await cli.commit_row(fake, 2, row)
        assert second.duplicate is True
