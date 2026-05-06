"""Tests for build_bucket_C_ap_it_ticket_pack (read-only, synthetic)."""
from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

from scripts import build_bucket_C_ap_it_ticket_pack as bcp


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _intake(vendor: str = "FedEx",
            channel: str = "fedex_billing_email",
            owner: str = "IT",
            change: str = "add_sender_to_AP_transport_rule",
            count: int = 2,
            top_root: str = "AP/2026/04") -> Dict[str, Any]:
    return {
        "section": "intake_channel_changes",
        "cohort_key": {"likely_vendor": vendor,
                       "candidate_intake_channel": channel},
        "affected_doc_count": count,
        "current_arrival_channel": "none",
        "candidate_intake_channel": channel,
        "recommended_intake_change": change,
        "owner_hint": owner,
        "top_square9_parent_roots": [[top_root, count]],
        "evidence_sample": [],
    }


def _plan(*intake: Dict[str, Any]) -> Dict[str, Any]:
    return {"intake_channel_changes": list(intake), "parity_exclusions": []}


def _summary(cur: float = 38.28, proj: float = 55.08,
             min_rate: float = 85.0,
             bucket_a_docs: int = 43) -> Dict[str, Any]:
    return {
        "min_match_rate_pct": min_rate,
        "key_counts": {
            "parity": {"match_rate_pct": cur, "matched_count": 98,
                       "square_count": 256, "hub_count": 304},
            "bucket_A": {"actionable_doc_count": bucket_a_docs,
                         "actionable_cohort_count": 5},
            "bucket_C": {},
            "projection": {"post_bucket_A_apply_match_rate_pct": proj},
        },
    }


# ---------------------------------------------------------------------------
# classify_cohort
# ---------------------------------------------------------------------------

def test_classify_it_transport_rule_uses_P1_taxonomy():
    t = bcp.classify_cohort(_intake())
    assert t["ticket_owner"] == "IT"
    assert t["recommended_action"] == "add_sender_to_AP_transport_rule"
    assert t["priority"] == "P1"
    assert t["issue_type"] == "intake_misroute_at_transport_layer"
    assert "transport" not in t["validation_expectation"].lower() or \
           "test message" in t["validation_expectation"].lower()


def test_classify_ap_alias_forward_uses_P1_taxonomy():
    t = bcp.classify_cohort(_intake(
        vendor="RLCarriers", channel="rl_carriers_email", owner="AP",
        change="forward_billing_alias_to_hub_ap_intake", count=2))
    assert t["ticket_owner"] == "AP"
    assert t["priority"] == "P1"
    assert t["issue_type"] == "intake_alias_not_forwarded"


def test_classify_ap_portal_download_uses_P2_taxonomy():
    t = bcp.classify_cohort(_intake(
        vendor="Cogent", channel="cogent_billing_portal", owner="AP",
        change="enable_portal_download", count=1))
    assert t["priority"] == "P2"
    assert t["issue_type"] == "intake_portal_download_required"


def test_classify_ap_manual_followup_uses_P2_taxonomy():
    t = bcp.classify_cohort(_intake(
        vendor="Tumalo", channel="monitored_ap_lane_unknown_sender",
        owner="AP", change="manual_followup", count=2))
    assert t["priority"] == "P2"
    assert t["issue_type"] == "intake_channel_unknown"


def test_classify_unknown_action_falls_back_to_default():
    t = bcp.classify_cohort(_intake(change="invent_new_thing"))
    assert t["priority"] == "P2"
    assert t["recommended_action"] == "invent_new_thing"


def test_classify_uses_unknown_vendor_label_when_blank():
    t = bcp.classify_cohort(_intake(vendor=""))
    assert t["vendor"] == "<unknown>"


def test_classify_extracts_top_square9_root():
    t = bcp.classify_cohort(_intake(top_root="Operations/2026/04"))
    assert t["source_square9_folder"] == "Operations/2026/04"


# ---------------------------------------------------------------------------
# partition_tickets
# ---------------------------------------------------------------------------

def test_partition_tickets_routes_owner_and_action_correctly():
    plan = _plan(
        _intake(vendor="FedEx", owner="IT",
                change="add_sender_to_AP_transport_rule", count=2),
        _intake(vendor="RL", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=1),
        _intake(vendor="Cogent", owner="AP",
                change="enable_portal_download", count=1),
        _intake(vendor="Tumalo", owner="AP",
                change="manual_followup", count=2),
    )
    tickets = bcp.build_tickets(plan)
    parts = bcp.partition_tickets(tickets)
    assert [r["vendor"] for r in parts["it"]] == ["FedEx"]
    assert [r["vendor"] for r in parts["ap_alias_forward"]] == ["RL"]
    assert [r["vendor"] for r in parts["ap_portal_download"]] == ["Cogent"]
    assert [r["vendor"] for r in parts["ap_manual_followup"]] == ["Tumalo"]


def test_partition_tickets_sorts_by_doc_count_desc_then_vendor():
    plan = _plan(
        _intake(vendor="A", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=1),
        _intake(vendor="B", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=5),
        _intake(vendor="C", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=5),
    )
    parts = bcp.partition_tickets(bcp.build_tickets(plan))
    assert [r["vendor"] for r in parts["ap_alias_forward"]] == \
           ["B", "C", "A"]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_render_csv_has_required_columns_in_order():
    plan = _plan(_intake())
    tickets = bcp.build_tickets(plan)
    body = bcp.render_csv(tickets)
    rows = list(csv.DictReader(StringIO(body)))
    assert list(rows[0].keys()) == bcp.CSV_COLUMNS
    r = rows[0]
    assert r["ticket_owner"] == "IT"
    assert r["vendor"] == "FedEx"
    assert r["affected_doc_count"] == "2"
    assert r["priority"] == "P1"
    assert r["issue_type"] == "intake_misroute_at_transport_layer"
    assert r["recommended_action"] == "add_sender_to_AP_transport_rule"


def test_render_csv_handles_empty_ticket_list():
    body = bcp.render_csv([])
    rows = list(csv.DictReader(StringIO(body)))
    assert rows == []


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def test_render_md_has_seven_required_sections_plus_email():
    plan = _plan(
        _intake(vendor="FedEx", owner="IT", count=2),
        _intake(vendor="RL", owner="AP", change="forward_billing_alias_to_hub_ap_intake", count=2),
        _intake(vendor="Cogent", owner="AP", change="enable_portal_download", count=1),
        _intake(vendor="Tumalo", owner="AP", change="manual_followup", count=2),
    )
    tickets = bcp.build_tickets(plan)
    md = bcp.render_md(_summary(), tickets, "p", "2026-05-06 21:30:00 UTC")
    assert "## 1. Executive summary" in md
    assert "## 2. IT ticket section" in md
    assert "## 3. AP ticket section" in md
    assert "## 4. Portal-download section" in md
    assert "## 5. Manual-followup section" in md
    assert "## 6. Explicit non-actions" in md
    assert "## 7. After-actions checklist" in md
    assert "## 8. Email draft" in md
    assert "FedEx" in md and "RL" in md and "Cogent" in md and "Tumalo" in md
    # Non-actions explicitly listed
    assert "No Square9 cutover yet" in md
    assert "No Bucket A data patch yet" in md
    assert "No removal of `square9@gamerpackaging.com`" in md


def test_render_md_executive_summary_uses_summary_numbers():
    plan = _plan(_intake())
    md = bcp.render_md(_summary(cur=38.28, proj=55.08), bcp.build_tickets(plan),
                       "p", "2026-05-06 21:30:00 UTC")
    assert "38.28%" in md
    assert "55.08%" in md
    assert "85.00%" in md


def test_render_md_handles_unknown_match_rates():
    summary = {"min_match_rate_pct": 85.0,
               "key_counts": {"parity": {}, "bucket_A": {},
                              "bucket_C": {}, "projection": {}}}
    md = bcp.render_md(summary, bcp.build_tickets(_plan(_intake())),
                       "p", "2026-05-06 21:30:00 UTC")
    assert "unknown" in md
    assert "## 1. Executive summary" in md


def test_render_md_emits_no_cohorts_placeholder_for_empty_section():
    plan = _plan(_intake(vendor="FedEx", owner="IT"))  # no AP
    md = bcp.render_md(_summary(), bcp.build_tickets(plan),
                       "p", "2026-05-06 21:30:00 UTC")
    assert "_(no ap — alias forward cohorts" in md.lower() or \
           "no AP — alias forward cohorts in this section" in md


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def test_render_email_includes_match_rates_and_owner_counts():
    plan = _plan(
        _intake(vendor="FedEx", owner="IT", count=2),
        _intake(vendor="RL", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=2),
    )
    tickets = bcp.build_tickets(plan)
    body = bcp.render_email(_summary(cur=38.28, proj=55.08), tickets)
    assert body.startswith("Subject:")
    assert "38.1%" in body or "38.3%" in body or "38.2%" in body
    assert "55.1%" in body
    assert "1 IT ticket" in body
    assert "1 AP ticket" in body
    assert "no production state has changed" in body.lower() or \
           "No production state has changed" in body


# ---------------------------------------------------------------------------
# write_outputs round-trip (tmp_path)
# ---------------------------------------------------------------------------

def test_write_outputs_creates_three_files(tmp_path: Path):
    plan = _plan(
        _intake(vendor="FedEx", owner="IT", count=2),
        _intake(vendor="RL", owner="AP",
                change="forward_billing_alias_to_hub_ap_intake", count=2),
    )
    tickets = bcp.build_tickets(plan)
    paths = bcp.write_outputs(str(tmp_path), _summary(), tickets,
                              "2026-05-06 21:30:00 UTC")
    assert (tmp_path / "BUCKET_C_AP_IT_TICKET_PACK.md").exists()
    assert (tmp_path / "BUCKET_C_AP_IT_TICKET_PACK.csv").exists()
    assert (tmp_path / "BUCKET_C_AP_IT_EMAIL_DRAFT.txt").exists()
    assert paths["md"].endswith("BUCKET_C_AP_IT_TICKET_PACK.md")
    csv_body = (tmp_path / "BUCKET_C_AP_IT_TICKET_PACK.csv").read_text(
        encoding="utf-8")
    rows = list(csv.DictReader(StringIO(csv_body)))
    assert {r["vendor"] for r in rows} == {"FedEx", "RL"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_returns_one_when_proof_dir_missing(tmp_path: Path, monkeypatch,
                                                 capsys):
    monkeypatch.setattr("sys.argv",
                        ["build", "--proof-dir", str(tmp_path / "nope")])
    rc = bcp.main()
    assert rc == 1


def test_cli_returns_two_when_no_intake_cohorts(tmp_path: Path, monkeypatch):
    parent = tmp_path
    proof_dir = parent / "cutover_proof_X"
    proof_dir.mkdir()
    (proof_dir / "summary.json").write_text(json.dumps(_summary()),
                                            encoding="utf-8")
    (parent / "bucket_C_remediation_plan.json").write_text(
        json.dumps({"intake_channel_changes": []}), encoding="utf-8")
    monkeypatch.setattr("sys.argv",
                        ["build", "--proof-dir", str(proof_dir)])
    rc = bcp.main()
    assert rc == 2


def test_cli_writes_outputs_and_returns_zero(tmp_path: Path, monkeypatch,
                                              capsys):
    parent = tmp_path
    proof_dir = parent / "cutover_proof_X"
    proof_dir.mkdir()
    (proof_dir / "summary.json").write_text(json.dumps(_summary()),
                                            encoding="utf-8")
    (parent / "bucket_C_remediation_plan.json").write_text(
        json.dumps(_plan(
            _intake(vendor="FedEx", owner="IT", count=2),
            _intake(vendor="RL", owner="AP",
                    change="forward_billing_alias_to_hub_ap_intake",
                    count=2),
        )),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv",
                        ["build", "--proof-dir", str(proof_dir)])
    rc = bcp.main()
    assert rc == 0
    assert (proof_dir / "BUCKET_C_AP_IT_TICKET_PACK.md").exists()
    assert (proof_dir / "BUCKET_C_AP_IT_TICKET_PACK.csv").exists()
    assert (proof_dir / "BUCKET_C_AP_IT_EMAIL_DRAFT.txt").exists()
    out = capsys.readouterr().out
    assert "READ-ONLY" in out
