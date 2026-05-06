"""Tests for ops/cutover_proof_summary.py (read-only, synthetic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Make ops/ importable for tests run from /app or /app/backend.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ops import cutover_proof_summary as cps  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _step(id_: str, label: str = "lbl", rc: int = 0,
          duration: int = 1) -> Dict[str, Any]:
    return {
        "id": id_,
        "label": label,
        "cmd": "python scripts/" + id_ + ".py",
        "rc": rc,
        "duration_sec": duration,
        "log_path": f"logs/{id_}.log",
    }


def _manifest(*steps: Dict[str, Any], proof_dir: str = "p") -> Dict[str, Any]:
    return {
        "proof_dir": proof_dir,
        "started_at_utc": "2026-05-06T18:00:00Z",
        "finished_at_utc": "2026-05-06T18:05:00Z",
        "min_match_rate_pct": 85.0,
        "steps": list(steps),
    }


# ---------------------------------------------------------------------------
# classify_step
# ---------------------------------------------------------------------------

def test_classify_step_rc_zero_is_ok():
    assert cps.classify_step(_step("a", rc=0)) == "ok"


def test_classify_step_rc_one_or_two_is_ok_signal():
    assert cps.classify_step(_step("a", rc=1)) == "ok_signal"
    assert cps.classify_step(_step("a", rc=2)) == "ok_signal"


def test_classify_step_rc_three_or_more_is_fail():
    assert cps.classify_step(_step("a", rc=3)) == "fail"
    assert cps.classify_step(_step("a", rc=137)) == "fail"


# ---------------------------------------------------------------------------
# match_rate extraction
# ---------------------------------------------------------------------------

def test_extract_match_rate_handles_pct_field():
    assert cps._extract_match_rate({"match_rate_pct": 91.3}) == 91.3


def test_extract_match_rate_handles_summary_nesting():
    payload = {"summary": {"match_rate_percent": 87.0}}
    assert cps._extract_match_rate(payload) == 87.0


def test_extract_match_rate_converts_zero_to_one_fraction():
    assert cps._extract_match_rate({"match_rate": 0.873}) == 87.3


def test_extract_match_rate_returns_none_when_absent():
    assert cps._extract_match_rate({}) is None
    assert cps._extract_match_rate({"unrelated": 1}) is None
    assert cps._extract_match_rate("not a dict") is None


def test_load_parity_match_rate_reads_from_proof_dir(tmp_path: Path):
    (tmp_path / "square9_hub_ap_parity.json").write_text(
        json.dumps({"match_rate_pct": 91.4}), encoding="utf-8")
    assert cps.load_parity_match_rate(str(tmp_path)) == 91.4


def test_load_parity_match_rate_returns_none_when_missing(tmp_path: Path):
    assert cps.load_parity_match_rate(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Decision engine
# ---------------------------------------------------------------------------

def test_derive_blockers_empty_when_all_steps_ok_and_rate_meets_threshold():
    m = _manifest(_step("a", rc=0), _step("b", rc=2))
    assert cps.derive_blockers(m, 91.3, 85.0) == []


def test_derive_blockers_records_failed_steps():
    m = _manifest(_step("a", rc=3, label="A"), _step("b", rc=0))
    blockers = cps.derive_blockers(m, 91.0, 85.0)
    assert any("step 'A' failed" in b and "rc=3" in b for b in blockers)


def test_derive_blockers_flags_missing_match_rate():
    m = _manifest(_step("a", rc=0))
    blockers = cps.derive_blockers(m, None, 85.0)
    assert any("match_rate_pct unavailable" in b for b in blockers)


def test_derive_blockers_flags_below_threshold_match_rate():
    m = _manifest(_step("a", rc=0))
    blockers = cps.derive_blockers(m, 80.0, 85.0)
    assert any("80.00" in b and "85.00" in b for b in blockers)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------

def test_build_summary_decision_GO_when_all_pass():
    m = _manifest(_step("a", rc=0), _step("b", rc=2))
    s = cps.build_summary(m, 91.3, 85.0)
    assert s["decision"] == "GO"
    assert s["blockers"] == []
    assert s["step_count_total"] == 2
    assert s["step_count_ok"] == 1
    assert s["step_count_ok_signal"] == 1
    assert s["step_count_fail"] == 0
    assert s["match_rate_pct"] == 91.3
    assert s["proof_dir"] == "p"


def test_build_summary_decision_NO_GO_on_any_failure():
    m = _manifest(_step("a", rc=0), _step("b", rc=3))
    s = cps.build_summary(m, 91.3, 85.0)
    assert s["decision"] == "NO-GO"
    assert len(s["blockers"]) == 1


def test_build_summary_decision_NO_GO_below_threshold():
    m = _manifest(_step("a", rc=0))
    s = cps.build_summary(m, 84.9, 85.0)
    assert s["decision"] == "NO-GO"
    assert s["step_count_fail"] == 0


def test_build_summary_decision_NO_GO_when_match_rate_unknown():
    m = _manifest(_step("a", rc=0))
    s = cps.build_summary(m, None, 85.0)
    assert s["decision"] == "NO-GO"
    assert any("unavailable" in b for b in s["blockers"])


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def test_render_markdown_includes_decision_and_step_table():
    summary = cps.build_summary(
        _manifest(_step("a", rc=0, label="alpha")), 91.3, 85.0)
    md = cps.render_markdown(summary)
    assert "**GO**" in md
    assert "alpha" in md
    assert "READ-ONLY proof pack" in md


def test_render_markdown_blockers_section_when_NO_GO():
    summary = cps.build_summary(_manifest(_step("a", rc=3, label="A")),
                                91.3, 85.0)
    md = cps.render_markdown(summary)
    assert "## Blockers" in md
    assert "**NO-GO**" in md


def test_render_text_contains_per_step_lines():
    summary = cps.build_summary(
        _manifest(_step("a", rc=0, label="alpha"),
                  _step("b", rc=2, label="bravo")),
        91.3, 85.0,
    )
    text = cps.render_text(summary)
    assert "DECISION: GO" in text
    assert "id=a" in text
    assert "id=b" in text


def test_render_text_handles_unknown_match_rate():
    summary = cps.build_summary(_manifest(_step("a", rc=0)), None, 85.0)
    text = cps.render_text(summary)
    assert "unknown" in text
    assert "DECISION: NO-GO" in text


# ---------------------------------------------------------------------------
# load_manifest round-trip (tmp_path)
# ---------------------------------------------------------------------------

def test_load_manifest_round_trip(tmp_path: Path):
    manifest = _manifest(_step("a", rc=0))
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = cps.load_manifest(str(p))
    assert loaded["steps"][0]["id"] == "a"
    assert loaded["steps"][0]["rc"] == 0


# ---------------------------------------------------------------------------
# CLI integration (invokes main() through argparse)
# ---------------------------------------------------------------------------

def test_cli_writes_summary_files_and_returns_zero_on_GO(tmp_path: Path,
                                                          capsys, monkeypatch):
    manifest = _manifest(_step("a", rc=0))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
    (tmp_path / "square9_hub_ap_parity.json").write_text(
        json.dumps({"match_rate_pct": 91.3}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["cutover_proof_summary",
                         "--proof-dir", str(tmp_path),
                         "--min-match-rate", "85.0"])
    rc = cps.main()
    assert rc == 0
    body = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "**GO**" in body
    payload = json.loads((tmp_path / "summary.json").read_text(
        encoding="utf-8"))
    assert payload["decision"] == "GO"


def test_cli_returns_one_on_NO_GO(tmp_path: Path, monkeypatch):
    manifest = _manifest(_step("a", rc=3))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest),
                                            encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["cutover_proof_summary",
                         "--proof-dir", str(tmp_path)])
    rc = cps.main()
    assert rc == 1
