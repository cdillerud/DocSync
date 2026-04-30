"""Phase 3.2B — Bragg real-world golden fixture regression.

Validates the Contract Intelligence pipeline against the Bragg supply-agreement
packet (DocuSign Navigator metadata export + signed PDF ground truth).

Structure:
  1. `TestNormalizerAgainstConnectSynthesis` — confirms what the CURRENT
     normalizer extracts when fed a Connect-SIM-shape derived from the
     metadata + PDF. These are regressions that should stay green as we
     evolve the code.
  2. `TestNavigatorMetadataDirectConsumption` — explicitly documents that
     the current normalizer CANNOT consume the Navigator xlsx row directly.
     Marked xfail(strict=True) so if someone adds Navigator support, the
     test automatically flips and we know to remove the xfail.
  3. `TestBCMatchingAmbiguity` — exercises the "two BC codes for Bragg"
     scenario. Confirms the current matcher silently picks the top one
     (documented gap). The xfail assertion shows what a fixed matcher
     should do.
  4. `TestKnownSchemaGaps` — xfail-tagged assertions capturing each gap
     listed in bragg_expected_normalized.json so they show up in pytest
     output as a gap inventory without failing CI.

No production code is modified by this phase. This file is documentation
in executable form.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from services.contracts.agreement_normalizer import normalize_envelope
from services.contracts.bc_agreement_matcher import (
    BCAgreementMatcher,
    InMemoryBCRepository,
)
from models.contracts import AgreementParty


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docusign" / "bragg"
METADATA_FIXTURE = FIXTURE_DIR / "bragg_metadata_export_redacted.json"
EXPECTED_FIXTURE = FIXTURE_DIR / "bragg_expected_normalized.json"


@pytest.fixture(scope="module")
def metadata() -> Dict[str, Any]:
    return json.loads(METADATA_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expected() -> Dict[str, Any]:
    return json.loads(EXPECTED_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sim_payload(metadata: Dict[str, Any]) -> Dict[str, Any]:
    return metadata["connect_sim_synthesis"]


@pytest.fixture(scope="module")
def normalized(sim_payload: Dict[str, Any]):
    return normalize_envelope(sim_payload, event_id="bragg-regression")


# =============================================================================
# 1. Normalizer regression — Connect SIM synthesis of Bragg packet
# =============================================================================

class TestNormalizerAgainstConnectSynthesis:

    def test_envelope_id_resolved(self, normalized, expected):
        assert (
            normalized.agreement.provider_envelope_id
            == expected["agreement"]["provider_envelope_id"]
        )

    def test_status_completed(self, normalized, expected):
        assert normalized.agreement.status == expected["agreement"]["status"]

    def test_title_preserved(self, normalized, expected):
        assert normalized.agreement.title == expected["agreement"]["title"]

    def test_expires_at_parsed_to_tz_aware_datetime(self, normalized):
        assert normalized.agreement.expires_at is not None
        assert normalized.agreement.expires_at.tzinfo is not None
        assert normalized.agreement.expires_at.year == 2028

    def test_completed_at_matches_execution_date(self, normalized):
        assert normalized.agreement.completed_at is not None
        assert normalized.agreement.completed_at.year == 2026
        assert normalized.agreement.completed_at.month == 4
        assert normalized.agreement.completed_at.day == 27

    def test_parties_include_both_orgs(self, normalized, expected):
        orgs = {p.organization for p in normalized.parties if p.organization}
        # Both Bragg and Gamer must appear at least once
        assert "Bragg Live Food Products LLC" in orgs
        assert "Gamer Packaging, Inc." in orgs

    def test_customer_normalized_org_matches_expected(self, normalized):
        # Canonical form for BC matching
        bragg = next(
            (p for p in normalized.parties
             if p.organization == "Bragg Live Food Products LLC"),
            None,
        )
        assert bragg is not None
        assert bragg.normalized_org == "bragg live food products llc"

    def test_term_keys_include_all_metadata_fields(self, normalized):
        keys = {t.term_key for t in normalized.terms}
        for required in (
            "agreement_type", "agreement_id_number", "effective_date",
            "execution_date", "expiration_date", "initial_term_length",
            "payment_term", "price_cap_increase_pct", "governing_law",
            "renewal_type", "renewal_term",
        ):
            assert required in keys, f"missing term_key: {required}"

    def test_term_agreement_type_value(self, normalized):
        t = next(t for t in normalized.terms if t.term_key == "agreement_type")
        assert t.term_value == "Supply / Distribution"
        assert t.source == "custom_field"

    def test_payment_term_full_text_from_pdf(self, normalized):
        """Proves the synthesized payload can carry the PDF's full text
        (`1% 10 / Net 45 Days`), even though Navigator truncated it to
        `45 days`. This is a documentation test — see the findings report."""
        t = next(t for t in normalized.terms if t.term_key == "payment_term")
        assert t.term_value == "1% 10 / Net 45 Days"

    def test_price_cap_6pct_captured(self, normalized):
        t = next(t for t in normalized.terms
                 if t.term_key == "price_cap_increase_pct")
        assert t.term_value == "6"

    def test_pricing_line_1_widget_bacv16g(self, normalized, expected):
        line = next(p for p in normalized.pricing if p.line_no == 1)
        exp = expected["pricing_minimum_signals"][0]
        assert line.item_label == exp["item_label"]
        assert line.quantity == exp["quantity"]
        assert line.unit_price == exp["unit_price"]
        assert line.uom == exp["uom"]

    def test_pricing_line_2_widget_bacv32g(self, normalized, expected):
        line = next(p for p in normalized.pricing if p.line_no == 2)
        exp = expected["pricing_minimum_signals"][1]
        assert line.item_label == exp["item_label"]
        assert line.quantity == exp["quantity"]
        assert line.unit_price == exp["unit_price"]
        assert line.uom == exp["uom"]

    def test_document_present(self, normalized):
        assert len(normalized.documents) >= 1
        assert normalized.documents[0].provider_document_id == "1"


# =============================================================================
# 2. Navigator xlsx row direct consumption — EXPECTED TO FAIL TODAY
# =============================================================================

class TestNavigatorMetadataDirectConsumption:

    def test_normalizer_can_read_raw_xlsx_row(self, metadata):
        """Phase 4A: ``normalize_envelope`` now detects a Navigator-shaped
        flat row and dispatches to ``navigator_normalizer.normalize_navigator_row``.
        The ingest produces the same ``NormalizedAgreement`` shape as the
        Connect path."""
        row = metadata["row"]
        result = normalize_envelope(row)
        # Envelope id preserved verbatim (case may vary on the SIM side
        # but the adapter copies it through without casing changes).
        assert result.agreement.provider_envelope_id == row["Envelope Id"]
        # Canonical Navigator UUID stored as a first-class field.
        assert result.agreement.provider_agreement_id == row["Agreement Id"]
        # Both party organizations surface as signer rows.
        orgs = {p.organization for p in result.parties if p.organization}
        assert "Bragg Live Food Products LLC" in orgs
        assert "Gamer Packaging, Inc." in orgs
        # Status maps from Navigator "Active" → canonical "completed".
        assert result.agreement.status == "completed"
        # Key metadata terms rendered as custom-field rows.
        term_keys = {t.term_key for t in result.terms}
        for required in (
            "agreement_type", "agreement_id_number", "payment_term",
            "governing_law", "initial_term_length", "renewal_type",
            "renewal_term", "price_cap_increase_pct",
        ):
            assert required in term_keys, f"missing Navigator term: {required}"


# =============================================================================
# 3. BC matching ambiguity — 2 Bragg customer codes
# =============================================================================

class TestBCMatchingAmbiguity:

    @pytest.mark.asyncio
    async def test_current_matcher_silently_picks_one(self, expected):
        """Documents CURRENT behavior: with two equally-scoring Bragg customer
        candidates, the matcher emits exactly ONE customer link; the other
        Bragg BC code is silently dropped. No ambiguous-match exception.
        """
        # Two BC candidates — both strong matches for "Bragg Live Food Products LLC"
        repo = InMemoryBCRepository(
            customers=[
                {"no": "C-BRAGG-E", "name": "Bragg Live Food Products LLC"},
                {"no": "C-BRAGG-W", "name": "Bragg Live Food Products LLC"},
            ],
        )
        matcher = BCAgreementMatcher(repo)
        bragg_party = AgreementParty(
            agreement_id="agr-bragg",
            role="signer",
            name="Redacted Name 2",
            organization="Bragg Live Food Products LLC",
        )
        result = await matcher.match(
            agreement_id="agr-bragg",
            parties=[bragg_party],
            pricing=[],
        )
        customer_links = [link for link in result.links
                          if link.link_type == "customer"]
        # Documented gap: exactly one link created.
        assert len(customer_links) == 1, (
            "current matcher collapses ambiguous candidates to a single link"
        )
        # And NO ambiguity-flagged exception is produced:
        ambiguous_exc = [
            e for e in result.exceptions
            if e.details.get("ambiguous") is True
        ]
        assert ambiguous_exc == [], (
            "current matcher does NOT signal ambiguity — tracked as a gap"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "AMBIGUITY GAP — the matcher should emit both candidates as "
            "proposed links AND open a high-severity party_unmatched exception "
            "with details.ambiguous=true. Not in scope for Phase 4A (payload "
            "reconciliation). Tracked for a follow-up matcher-hardening pass."
        ),
    )
    async def test_ambiguous_match_emits_both_plus_exception(self):
        repo = InMemoryBCRepository(
            customers=[
                {"no": "C-BRAGG-E", "name": "Bragg Live Food Products LLC"},
                {"no": "C-BRAGG-W", "name": "Bragg Live Food Products LLC"},
            ],
        )
        matcher = BCAgreementMatcher(repo)
        party = AgreementParty(
            agreement_id="agr-bragg", role="signer",
            name="Redacted Name 2",
            organization="Bragg Live Food Products LLC",
        )
        result = await matcher.match(
            agreement_id="agr-bragg", parties=[party], pricing=[],
        )
        links = [link for link in result.links if link.link_type == "customer"]
        bc_nos = {link.bc_no for link in links}
        assert bc_nos == {"C-BRAGG-E", "C-BRAGG-W"}
        assert any(e.details.get("ambiguous") is True for e in result.exceptions)


# =============================================================================
# 4. Schema-gap inventory — each xfail surfaces a tracked recommendation
# =============================================================================

class TestKnownSchemaGaps:

    def test_navigator_uuid_is_first_class_field(self, metadata, expected):
        """Phase 4A: ``Agreement.provider_agreement_id`` now holds the
        Navigator UUID. The Navigator-path ingest populates it directly
        from the ``Agreement Id`` column."""
        from services.contracts.navigator_normalizer import normalize_navigator_row
        nav_result = normalize_navigator_row(
            metadata, event_id="bragg-schema-gap-check",
        )
        assert (
            nav_result.agreement.provider_agreement_id
            == expected["agreement"]["provider_agreement_id_navigator"]
        )

    def test_alternate_envelope_id_captured(self, normalized, expected):
        """Phase 4A: Agreement.alternate_envelope_ids now captures any
        alternate id DocuSign stamps into the envelope summary (or surfaces
        as an alternate_envelope_id custom field). The Bragg Connect-SIM
        fixture was updated to carry the PDF-visible alt id."""
        alts = normalized.agreement.alternate_envelope_ids
        assert isinstance(alts, list)
        assert expected["agreement"]["alternate_envelope_ids"][0].lower() in [
            x.lower() for x in alts
        ]

    def test_pricing_row_has_location_field(self, normalized):
        """Phase 4A: AgreementPricing now has a ``location`` field; the
        pricing extractor picks up ``line_N_location`` tabs."""
        line = next(p for p in normalized.pricing if p.line_no == 1)
        assert line.location == "Garden Grove, CA"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FIELD GAP — Navigator xlsx row does NOT carry the 1% 10 payment "
            "discount. Only the PDF body does. Phase 4A does not split "
            "`payment_term` into discount + net on its own — the canonical "
            "fix is a DocuSign template change that exposes an explicit "
            "`payment_term_discount` custom field. Tracked for template "
            "rollout; xfail kept so it flips automatically once the field "
            "arrives on a live envelope."
        ),
    )
    def test_payment_term_discount_exposed_as_own_term(self, normalized):
        keys = [t.term_key for t in normalized.terms]
        assert "payment_term_discount" in keys


# =============================================================================
# 5. Harness sanity
# =============================================================================

class TestHarness:
    def test_both_fixtures_exist(self):
        assert METADATA_FIXTURE.is_file()
        assert EXPECTED_FIXTURE.is_file()

    def test_metadata_row_has_54_columns(self, metadata):
        # Pins the Navigator schema we're regression-testing against.
        assert len(metadata["row"]) == 54

    def test_metadata_envelope_id_matches_expected(self, metadata, expected):
        assert (
            metadata["row"]["Envelope Id"]
            == expected["agreement"]["provider_envelope_id"]
        )

    def test_metadata_agreement_id_uuid_matches_expected(self, metadata, expected):
        assert (
            metadata["row"]["Agreement Id"]
            == expected["agreement"]["provider_agreement_id_navigator"]
        )
