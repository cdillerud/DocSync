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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SCHEMA GAP — Navigator AI Metadata Export is not a Connect SIM "
            "payload. Current normalizer.normalize_envelope() does not know "
            "how to read the flat row shape. Recommended fix: ship a "
            "navigator_normalizer.py adapter in Phase 4.x. If this xfail ever "
            "flips to pass, delete it and graduate the behavior."
        ),
    )
    def test_normalizer_can_read_raw_xlsx_row(self, metadata):
        row = metadata["row"]
        # This will raise ValueError (missing envelopeId) because the flat row
        # has "Envelope Id" (with space) not "envelopeId" nested inside
        # data.envelopeSummary. The normalizer's own discovery path does not
        # look at top-level human-readable column names.
        result = normalize_envelope(row)
        # If we ever get here, great — these are what we'd want to confirm:
        assert result.agreement.provider_envelope_id == row["Envelope Id"]


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
            "with details.ambiguous=true. Recommended fix scope: Phase 4.x "
            "matcher hardening. Flip xfail to pass once implemented."
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

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SCHEMA GAP — Agreement model has no `provider_agreement_id` "
            "field to store the Navigator UUID (0bebdb15-...). Currently "
            "stored as a term with key='agreement_id_number' instead. "
            "Recommended: add dedicated Agreement.provider_agreement_id."
        ),
    )
    def test_navigator_uuid_is_first_class_field(self, normalized, expected):
        # Note: field doesn't exist today, so attribute access raises.
        nav_uuid = normalized.agreement.provider_agreement_id  # type: ignore[attr-defined]
        assert nav_uuid == expected["agreement"]["provider_agreement_id_navigator"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SCHEMA GAP — Agreement model has no `alternate_envelope_ids` "
            "list. Bragg PDF shows a second DocuSign envelope id in the "
            "signed trail (A535A3EE-7BBA-8E79-81DC-09A99ECC3D95). "
            "Recommended: add Agreement.alternate_envelope_ids: list[str]."
        ),
    )
    def test_alternate_envelope_id_captured(self, normalized, expected):
        alts = normalized.agreement.alternate_envelope_ids  # type: ignore[attr-defined]
        assert expected["agreement"]["alternate_envelope_ids"][0].lower() in [
            x.lower() for x in alts
        ]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SCHEMA GAP — AgreementPricing has no `location` field. "
            "Bragg supply schedule specifies per-line ship-to location "
            "(Garden Grove, CA). Recommended: add AgreementPricing.location."
        ),
    )
    def test_pricing_row_has_location_field(self, normalized):
        line = next(p for p in normalized.pricing if p.line_no == 1)
        assert line.location == "Garden Grove, CA"  # type: ignore[attr-defined]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FIELD GAP — Navigator xlsx row does NOT carry the "
            "1% 10 payment discount. Only the PDF body does. Recommended: "
            "add explicit `payment_term_discount` custom-field to the "
            "DocuSign template and expose separately from `payment_term`."
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
