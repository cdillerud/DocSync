"""Tests for ops/cutover_proof_summary.py (read-only, synthetic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Make backend/ importable so `from ops import cutover_proof_summary` works
# regardless of pytest invocation cwd.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

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


def test_classify_step_traceback_in_log_overrides_rc_one(tmp_path: Path):
    log = tmp_path / "step.log"
    log.write_text(
        "Loaded 12 docs.\n"
        "Traceback (most recent call last):\n"
        "  File 'x.py', line 1, in <module>\n"
        "FileNotFoundError: missing.csv\n",
        encoding="utf-8",
    )
    step = _step("a", rc=1)
    step["log_path"] = str(log)
    assert cps.classify_step(step) == "fail"


def test_classify_step_no_traceback_keeps_rc_one_as_ok_signal(tmp_path: Path):
    log = tmp_path / "step.log"
    log.write_text("workflow signal — no rows emitted\n",
                   encoding="utf-8")
    step = _step("a", rc=1)
    step["log_path"] = str(log)
    assert cps.classify_step(step) == "ok_signal"


def test_step_log_has_traceback_returns_false_when_log_missing():
    step = _step("a", rc=1)
    step["log_path"] = "/nonexistent/path.log"
    assert cps.step_log_has_traceback(step) is False


def test_derive_blockers_marks_traceback_steps(tmp_path: Path):
    log = tmp_path / "step.log"
    log.write_text("Traceback (most recent call last):\n"
                   "FileNotFoundError: missing.csv\n",
                   encoding="utf-8")
    step = _step("a", rc=1, label="A")
    step["log_path"] = str(log)
    m = _manifest(step)
    blockers = cps.derive_blockers(m, 91.3, 85.0)
    assert any("Python traceback in log" in b for b in blockers)


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


def test_load_parity_match_rate_reads_from_step_log_when_json_only(tmp_path: Path):
    """The parity script prints JSON to stdout when run with --json; the
    orchestrator captures stdout into the step log file. The summarizer
    must accept that .log as a valid JSON source."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "square9_hub_ap_parity_report.log").write_text(
        json.dumps({"match_rate": 0.913, "blockers": []}), encoding="utf-8")
    rate = cps.load_parity_match_rate(str(tmp_path))
    assert rate is not None
    assert abs(rate - 91.3) < 1e-6


def test_load_parity_match_rate_prefers_proof_dir_json_over_log(tmp_path: Path):
    (tmp_path / "square9_hub_ap_parity.json").write_text(
        json.dumps({"match_rate_pct": 92.0}), encoding="utf-8")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "square9_hub_ap_parity_report.log").write_text(
        json.dumps({"match_rate": 0.50}), encoding="utf-8")
    assert cps.load_parity_match_rate(str(tmp_path)) == 92.0


def test_load_parity_match_rate_tolerates_preamble_in_log(tmp_path: Path):
    """The parity script prints progress prose to stderr before the
    --json payload. The orchestrator captures stdout+stderr together,
    so the log file starts with a few lines of preamble and ONLY THEN
    contains the JSON object. The parser must scan past the preamble."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    body = (
        "Graph token acquired. Host: example.sharepoint.com\n"
        "  graph-pull[prod]: visited 247 folder(s), 3362 file(s).\n"
        "Square9 listing: 3362 total, 87 within last 24h.\n"
        "Loaded 87 Square9 docs, 296 Hub AP docs.\n"
        + json.dumps({"match_rate": 0.5172, "blockers": []})
    )
    (logs_dir / "square9_hub_ap_parity_report.log").write_text(
        body, encoding="utf-8")
    rate = cps.load_parity_match_rate(str(tmp_path))
    assert rate is not None
    assert abs(rate - 51.72) < 1e-2


def test_try_parse_json_file_returns_none_on_garbage(tmp_path: Path):
    p = tmp_path / "bad.log"
    p.write_text("no json anywhere here\njust prose\n", encoding="utf-8")
    assert cps._try_parse_json_file(str(p)) is None


def test_try_parse_json_file_returns_none_on_missing(tmp_path: Path):
    assert cps._try_parse_json_file(str(tmp_path / "nope.log")) is None


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


# ---------------------------------------------------------------------------
# Key counts + projection
# ---------------------------------------------------------------------------

def test_build_key_counts_projects_match_rate_after_bucket_A_apply():
    parity = {"square_count": 1000, "hub_count": 800,
              "bucket_counts": {"matched": 360, "square9_only": 640}}
    bucket_a = {"cohort_count_actionable": 11,
                "actionable_doc_count": 500,
                "cohort_count_manual_review": 4}
    bucket_c = {"intake_channel_change_cohort_count": 7,
                "parity_exclusion_cohort_count": 2}
    kc = cps.build_key_counts(parity, bucket_a, bucket_c, 36.0)
    assert kc["parity"]["matched_count"] == 360
    assert kc["bucket_A"]["actionable_doc_count"] == 500
    assert kc["bucket_C"]["intake_channel_change_cohort_count"] == 7
    proj = kc["projection"]["post_bucket_A_apply_match_rate_pct"]
    # (360 + 500) / 1000 = 86.0
    assert abs(proj - 86.0) < 1e-6
    assert "matched=360" in kc["projection"]["basis"]


def test_build_key_counts_handles_all_missing():
    kc = cps.build_key_counts(None, None, None, None)
    assert kc["parity"]["square_count"] is None
    assert kc["parity"]["matched_count"] is None
    assert kc["bucket_A"]["actionable_doc_count"] is None
    assert kc["projection"]["post_bucket_A_apply_match_rate_pct"] is None


def test_build_key_counts_skips_projection_when_inputs_missing():
    parity = {"square_count": 1000,
              "bucket_counts": {"matched": 360}}
    kc = cps.build_key_counts(parity, None, None, 36.0)
    assert kc["projection"]["post_bucket_A_apply_match_rate_pct"] is None


def test_build_key_counts_skips_projection_when_square_count_zero():
    parity = {"square_count": 0,
              "bucket_counts": {"matched": 0}}
    bucket_a = {"actionable_doc_count": 5}
    kc = cps.build_key_counts(parity, bucket_a, None, 0.0)
    assert kc["projection"]["post_bucket_A_apply_match_rate_pct"] is None


def test_render_text_includes_key_counts_block():
    parity = {"square_count": 100, "hub_count": 80,
              "bucket_counts": {"matched": 36, "square9_only": 64}}
    bucket_a = {"cohort_count_actionable": 11,
                "actionable_doc_count": 50,
                "cohort_count_manual_review": 4}
    bucket_c = {"intake_channel_change_cohort_count": 7,
                "parity_exclusion_cohort_count": 2}
    summary = cps.build_summary(_manifest(_step("a", rc=0)),
                                36.0, 85.0,
                                parity_payload=parity,
                                bucket_a_plan=bucket_a,
                                bucket_c_plan=bucket_c)
    text = cps.render_text(summary)
    assert "KEY COUNTS:" in text
    assert "parity.square_count" in text
    assert "bucket_A.actionable_docs" in text
    assert "bucket_C.intake_change_cohrts" in text
    assert "PROJECTED MATCH RATE AFTER BUCKET A APPLY" in text
    # (36+50)/100 = 86%
    assert "86.00%" in text


def test_render_text_projection_tags_ge_threshold_as_clearing_gate():
    parity = {"square_count": 100,
              "bucket_counts": {"matched": 60}}
    bucket_a = {"actionable_doc_count": 30}
    summary = cps.build_summary(_manifest(_step("a", rc=0)),
                                60.0, 85.0,
                                parity_payload=parity,
                                bucket_a_plan=bucket_a,
                                bucket_c_plan=None)
    text = cps.render_text(summary)
    # 90% >= 85% -> clears gate
    assert "should clear the gate" in text


def test_render_text_projection_tags_below_threshold_as_insufficient():
    parity = {"square_count": 100,
              "bucket_counts": {"matched": 36}}
    bucket_a = {"actionable_doc_count": 20}
    summary = cps.build_summary(_manifest(_step("a", rc=0)),
                                36.0, 85.0,
                                parity_payload=parity,
                                bucket_a_plan=bucket_a,
                                bucket_c_plan=None)
    text = cps.render_text(summary)
    # 56% < 85% -> not sufficient
    assert "NOT sufficient" in text


def test_render_markdown_includes_key_counts_table():
    parity = {"square_count": 100,
              "bucket_counts": {"matched": 36}}
    bucket_a = {"actionable_doc_count": 50,
                "cohort_count_actionable": 11}
    summary = cps.build_summary(_manifest(_step("a", rc=0)),
                                36.0, 85.0,
                                parity_payload=parity,
                                bucket_a_plan=bucket_a)
    md = cps.render_markdown(summary)
    assert "## Key counts" in md
    assert "| parity.square_count | 100 |" in md
    assert "| bucket_A.actionable_docs | 50 |" in md
    assert "Projected match rate after Bucket A apply" in md


def test_load_parity_payload_returns_full_dict(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    body = ("preamble line\n"
            + json.dumps({"square_count": 99,
                          "bucket_counts": {"matched": 33}}))
    (logs / "square9_hub_ap_parity_report.log").write_text(body,
                                                           encoding="utf-8")
    payload = cps.load_parity_payload(str(tmp_path))
    assert payload is not None
    assert payload["square_count"] == 99


def test_load_remediation_plan_returns_none_when_missing(tmp_path: Path):
    assert cps.load_remediation_plan(str(tmp_path / "nope.json")) is None


def test_load_remediation_plan_returns_dict_for_valid_json(tmp_path: Path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"actionable_doc_count": 42}), encoding="utf-8")
    plan = cps.load_remediation_plan(str(p))
    assert plan is not None
    assert plan["actionable_doc_count"] == 42
