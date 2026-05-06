"""Tests for bucket_C_handoff_doc (read-only, synthetic)."""
from __future__ import annotations

import csv
from typing import Any, Dict, List

import pytest  # noqa: F401  (kept for fixture extension consistency)

from scripts import bucket_C_handoff_doc as bc_handoff


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _intake(vendor: str = "FedEx",
            channel: str = "fedex_billing_email",
            owner: str = "IT",
            change: str = "add_sender_to_AP_transport_rule",
            count: int = 4,
            top_root: str = "AP/2026/04",
            sample_name: str = "fedex_inv_001.pdf") -> Dict[str, Any]:
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
        "evidence_sample": [
            {"square9_name": sample_name,
             "square9_parent_path": top_root,
             "filename_pattern": "billing"},
        ],
    }


def _exclusion(doc_type: str = "PST",
               count: int = 7,
               reason: str = "treasury_or_template",
               top_root: str = "Operations/Templates") -> Dict[str, Any]:
    return {
        "section": "parity_exclusions",
        "cohort_key": {"doc_type_guess": doc_type},
        "affected_doc_count": count,
        "exclusion_reason": reason,
        "recommended_intake_change": "exclude_from_parity_denominator",
        "owner_hint": "AP",
        "top_square9_parent_roots": [[top_root, count]],
        "evidence_sample": [
            {"square9_name": "vault_archive.pst",
             "square9_parent_path": top_root,
             "filename_pattern": "PST"},
        ],
    }


def _plan(intake: List[Dict[str, Any]],
          exclusions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total_bucket_C_rows": sum(i.get("affected_doc_count", 0)
                                   for i in intake + exclusions),
        "parity_exclusion_row_count": sum(c.get("affected_doc_count", 0)
                                          for c in exclusions),
        "real_intake_gap_row_count": sum(c.get("affected_doc_count", 0)
                                         for c in intake),
        "parity_exclusion_cohort_count": len(exclusions),
        "intake_channel_change_cohort_count": len(intake),
        "recommended_intake_change_counts": [],
        "owner_hint_counts": [],
        "parity_exclusions": exclusions,
        "intake_channel_changes": intake,
    }


# ---------------------------------------------------------------------------
# Owner grouping
# ---------------------------------------------------------------------------

def test_group_intake_by_owner_separates_IT_and_AP():
    plan = _plan(
        intake=[
            _intake(owner="IT", count=4),
            _intake(vendor="RL", channel="rl_carriers_email", owner="AP",
                    change="forward_billing_alias_to_hub_ap_intake", count=2),
            _intake(vendor="OI", channel="oi_packaging_solutions_email",
                    owner="IT", count=10),
        ],
        exclusions=[],
    )
    grouped = bc_handoff.group_intake_by_owner(plan)
    assert set(grouped) == {"IT", "AP"}
    assert len(grouped["IT"]) == 2
    assert len(grouped["AP"]) == 1
    assert grouped["IT"][0]["affected_doc_count"] == 10  # sorted desc


def test_group_intake_by_owner_defaults_unknown_owner_to_AP():
    plan = _plan(intake=[_intake(owner="")], exclusions=[])
    grouped = bc_handoff.group_intake_by_owner(plan)
    assert grouped["AP"] and len(grouped["AP"]) == 1


# ---------------------------------------------------------------------------
# CSV row builders
# ---------------------------------------------------------------------------

def test_cohort_to_csv_row_carries_owner_and_counts():
    row = bc_handoff.cohort_to_csv_row(_intake())
    assert row["section"] == "intake_channel_changes"
    assert row["owner_hint"] == "IT"
    assert row["likely_vendor"] == "FedEx"
    assert row["recommended_intake_change"] == "add_sender_to_AP_transport_rule"
    assert row["affected_doc_count"] == 4
    assert row["top_square9_parent_root"] == "AP/2026/04"
    assert row["evidence_sample_count"] == 1


def test_exclusion_to_csv_row_uses_exclusion_taxonomy():
    row = bc_handoff.exclusion_to_csv_row(_exclusion())
    assert row["section"] == "parity_exclusions"
    assert row["recommended_intake_change"] == "exclude_from_parity_denominator"
    assert row["doc_type_guess"] == "PST"
    assert row["exclusion_reason"] == "treasury_or_template"
    assert row["affected_doc_count"] == 7


def test_build_csv_rows_orders_IT_first_then_AP_then_exclusions():
    plan = _plan(
        intake=[_intake(vendor="V_AP", owner="AP"),
                _intake(vendor="V_IT", owner="IT")],
        exclusions=[_exclusion(doc_type="PST")],
    )
    rows = bc_handoff.build_csv_rows(plan)
    sections = [r["section"] for r in rows]
    assert sections == ["intake_channel_changes",
                        "intake_channel_changes",
                        "parity_exclusions"]
    owners = [r["owner_hint"] for r in rows[:2]]
    assert owners == ["IT", "AP"]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def test_render_markdown_contains_owner_sections_and_exclusions():
    plan = _plan(
        intake=[_intake(vendor="FedEx", owner="IT", count=4),
                _intake(vendor="RL", owner="AP", count=2,
                        channel="rl_carriers_email",
                        change="forward_billing_alias_to_hub_ap_intake")],
        exclusions=[_exclusion(doc_type="PST", count=7)],
    )
    grouped = bc_handoff.group_intake_by_owner(plan)
    md = bc_handoff.render_markdown(plan, grouped, "2026-02-15 12:00:00 UTC")
    assert "# Bucket C — Hub Intake Handoff" in md
    assert "_Generated: 2026-02-15 12:00:00 UTC_" in md
    assert "## IT actions" in md
    assert "## AP actions" in md
    assert "## Parity exclusions" in md
    assert "FedEx" in md and "RL" in md
    assert "add_sender_to_AP_transport_rule" in md
    assert "exclude_from_parity_denominator" not in md  # md uses prose
    assert "PST" in md
    assert "## Cutover checklist" in md


def test_render_markdown_emits_empty_state_when_owner_has_no_cohorts():
    plan = _plan(intake=[_intake(owner="IT")], exclusions=[])
    grouped = bc_handoff.group_intake_by_owner(plan)
    md = bc_handoff.render_markdown(plan, grouped, "2026-02-15 12:00:00 UTC")
    assert "_No AP cohorts in this plan._" in md


def test_render_markdown_handles_empty_plan():
    plan = _plan(intake=[], exclusions=[])
    grouped = bc_handoff.group_intake_by_owner(plan)
    md = bc_handoff.render_markdown(plan, grouped, "2026-02-15 12:00:00 UTC")
    assert "_No IT cohorts in this plan._" in md
    assert "_No AP cohorts in this plan._" in md
    assert "_No parity exclusions detected._" in md


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_exit_code_zero_for_empty_plan():
    plan = _plan(intake=[], exclusions=[])
    grouped = bc_handoff.group_intake_by_owner(plan)
    assert bc_handoff._exit_code(plan, grouped) == 0


def test_exit_code_one_when_only_exclusions_present():
    plan = _plan(intake=[], exclusions=[_exclusion()])
    grouped = bc_handoff.group_intake_by_owner(plan)
    assert bc_handoff._exit_code(plan, grouped) == 1


def test_exit_code_two_when_intake_cohorts_present():
    plan = _plan(intake=[_intake()], exclusions=[])
    grouped = bc_handoff.group_intake_by_owner(plan)
    assert bc_handoff._exit_code(plan, grouped) == 2


# ---------------------------------------------------------------------------
# Round-trip MD / CSV IO (tmp_path)
# ---------------------------------------------------------------------------

def test_md_and_csv_round_trip(tmp_path):
    plan = _plan(
        intake=[_intake(vendor="FedEx", owner="IT", count=4),
                _intake(vendor="RL", owner="AP", count=2,
                        channel="rl_carriers_email",
                        change="forward_billing_alias_to_hub_ap_intake")],
        exclusions=[_exclusion(doc_type="PST", count=7)],
    )
    grouped = bc_handoff.group_intake_by_owner(plan)
    md = bc_handoff.render_markdown(plan, grouped, "2026-02-15 12:00:00 UTC")
    csv_rows = bc_handoff.build_csv_rows(plan)

    md_path = tmp_path / "handoff.md"
    csv_path = tmp_path / "handoff.csv"
    bc_handoff.write_md(str(md_path), md)
    bc_handoff.write_csv(str(csv_path), csv_rows)

    body = md_path.read_text(encoding="utf-8")
    assert "## IT actions" in body
    assert "## AP actions" in body

    with csv_path.open(encoding="utf-8") as f:
        loaded = list(csv.DictReader(f))
    sections = [r["section"] for r in loaded]
    assert sections.count("intake_channel_changes") == 2
    assert sections.count("parity_exclusions") == 1
    affected = sum(int(r["affected_doc_count"]) for r in loaded)
    assert affected == 4 + 2 + 7
