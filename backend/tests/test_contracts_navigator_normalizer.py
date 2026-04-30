"""Phase 4A — DocuSign Navigator AI Metadata Export adapter tests.

Isolates the flat-row → Connect-SIM translation so Navigator ingest can
be regression-tested independently of the Connect path. Uses the same
Bragg fixture as ``test_contracts_bragg_fixture.py`` for a real-world
column set.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from services.contracts.agreement_normalizer import normalize_envelope
from services.contracts.navigator_normalizer import (
    build_connect_sim_payload,
    normalize_navigator_row,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "docusign"
    / "bragg"
    / "bragg_metadata_export_redacted.json"
)


@pytest.fixture(scope="module")
def bragg_export() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# =============================================================================
# Connect SIM synthesis
# =============================================================================

class TestConnectSimSynthesis:

    def test_synthesis_preserves_envelope_id(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        assert (
            sim["data"]["envelopeSummary"]["envelopeId"]
            == bragg_export["row"]["Envelope Id"]
        )

    def test_synthesis_carries_navigator_uuid_as_hint(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        summary = sim["data"]["envelopeSummary"]
        assert summary.get("providerAgreementId") == bragg_export["row"]["Agreement Id"]

    def test_synthesis_maps_status_active_to_completed(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        assert sim["data"]["envelopeSummary"]["status"] == "completed"

    def test_synthesis_emits_both_parties_as_signers(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        signers = sim["data"]["envelopeSummary"]["recipients"]["signers"]
        orgs = {s["companyName"] for s in signers}
        assert "Bragg Live Food Products LLC" in orgs
        assert "Gamer Packaging, Inc." in orgs

    def test_synthesis_emits_term_custom_fields(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        fields = {
            f["name"]: f["value"]
            for f in sim["data"]["envelopeSummary"]["customFields"]["textCustomFields"]
        }
        assert fields["agreement_type"] == "Supply / Distribution"
        assert fields["governing_law"] == "California"
        assert fields["payment_term"] == "45 days"
        assert fields["price_cap_increase_pct"] == "6"
        assert fields["initial_term_length"] == "3 Years"
        assert fields["renewal_type"] == "Automatic Renewal"
        assert fields["renewal_term"] == "1 Years"
        assert fields["extension_period"] == "1 Years"
        assert fields["provider_agreement_id"] == bragg_export["row"]["Agreement Id"]

    def test_synthesis_drops_null_columns(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        fields = {
            f["name"]: f["value"]
            for f in sim["data"]["envelopeSummary"]["customFields"]["textCustomFields"]
        }
        # NULL columns in the Navigator row are absent from the synthesized
        # custom-field list (no empty-string leaks).
        assert "liability_cap_amount" not in fields
        assert "annual_contract_value" not in fields

    def test_synthesis_attaches_document_by_filename(self, bragg_export):
        sim = build_connect_sim_payload(bragg_export)
        docs = sim["data"]["envelopeSummary"]["envelopeDocuments"]
        assert len(docs) == 1
        assert docs[0]["documentId"] == "1"
        assert "Bragg" in docs[0]["name"]


# =============================================================================
# End-to-end: Navigator row → NormalizedAgreement
# =============================================================================

class TestNavigatorEndToEnd:

    def test_normalize_navigator_row_returns_agreement(self, bragg_export):
        result = normalize_navigator_row(bragg_export, event_id="nav::bragg")
        assert result.agreement.provider_envelope_id == bragg_export["row"]["Envelope Id"]
        assert result.agreement.provider_agreement_id == bragg_export["row"]["Agreement Id"]
        assert result.agreement.status == "completed"
        assert result.agreement.title == "Supply & Purchase Offer Agreement"

    def test_normalize_picks_expiration_from_navigator(self, bragg_export):
        result = normalize_navigator_row(bragg_export)
        assert result.agreement.expires_at is not None
        assert result.agreement.expires_at.year == 2028
        assert result.agreement.expires_at.tzinfo is not None

    def test_normalize_marks_event_id_when_missing(self, bragg_export):
        result = normalize_navigator_row(bragg_export)
        assert result.agreement.last_event_id
        assert "navigator::" in result.agreement.last_event_id

    def test_normalize_preserves_explicit_event_id(self, bragg_export):
        result = normalize_navigator_row(bragg_export, event_id="custom-evt-1")
        assert result.agreement.last_event_id == "custom-evt-1"

    def test_terms_cover_core_metadata(self, bragg_export):
        result = normalize_navigator_row(bragg_export)
        keys = {t.term_key for t in result.terms}
        for required in (
            "agreement_type", "agreement_id_number", "payment_term",
            "governing_law", "initial_term_length", "renewal_type",
            "renewal_term", "price_cap_increase_pct", "provider_agreement_id",
        ):
            assert required in keys, f"missing Navigator term: {required}"

    def test_parties_include_both_orgs_with_normalized_form(self, bragg_export):
        result = normalize_navigator_row(bragg_export)
        normalized_orgs = {p.normalized_org for p in result.parties if p.normalized_org}
        assert "bragg live food products llc" in normalized_orgs
        assert "gamer packaging inc" in normalized_orgs

    def test_navigator_row_has_no_pricing_rows(self, bragg_export):
        # Navigator AI Metadata Export does not carry line-level pricing —
        # the adapter must return an empty pricing list rather than
        # fabricate rows.
        result = normalize_navigator_row(bragg_export)
        assert result.pricing == []

    def test_missing_emails_surface_as_warnings(self, bragg_export):
        result = normalize_navigator_row(bragg_export)
        codes = [w.get("code") for w in result.warnings]
        # Connect-path normalizer warns on any signer without an email —
        # Navigator has none, so every signer should emit one.
        assert codes.count("party_missing_email") >= 2


# =============================================================================
# Dispatch via normalize_envelope
# =============================================================================

class TestDispatchFromUnifiedEntryPoint:

    def test_normalize_envelope_routes_flat_row_to_navigator(self, bragg_export):
        """``normalize_envelope`` should recognize a Navigator row and
        produce the same result as calling the adapter directly."""
        direct = normalize_navigator_row(bragg_export)
        dispatched = normalize_envelope(bragg_export["row"])
        assert (
            dispatched.agreement.provider_envelope_id
            == direct.agreement.provider_envelope_id
        )
        assert (
            dispatched.agreement.provider_agreement_id
            == direct.agreement.provider_agreement_id
        )
        assert {t.term_key for t in dispatched.terms} == {
            t.term_key for t in direct.terms
        }

    def test_normalize_envelope_still_accepts_connect_sim(self):
        """The Connect SIM path must remain untouched by the dispatcher."""
        connect_payload = {
            "event": "envelope-completed",
            "data": {
                "envelopeSummary": {
                    "envelopeId": "unit-test-env",
                    "status": "completed",
                    "recipients": {"signers": []},
                }
            },
        }
        result = normalize_envelope(connect_payload)
        assert result.agreement.provider_envelope_id == "unit-test-env"
        assert result.agreement.status == "completed"


# =============================================================================
# Negative cases
# =============================================================================

class TestAdapterEdgeCases:

    def test_raises_when_envelope_id_missing(self):
        with pytest.raises(ValueError, match="Envelope Id"):
            build_connect_sim_payload({
                "Agreement Type": "MSA",
                "Parties": "A;B",
                "Customer Name": "A",
            })

    def test_unknown_status_logs_warning(self):
        warnings: list = []
        sim = build_connect_sim_payload(
            {
                "Envelope Id": "env-xyz",
                "Agreement Type": "MSA",
                "Parties": "Alpha Co;Beta LLC",
                "Customer Name": "Alpha Co",
                "Status": "ZZZ-not-a-real-status",
            },
            warnings_sink=warnings,
        )
        codes = {w["code"] for w in warnings}
        assert "navigator_unknown_status" in codes
        # Envelope still emitted with mapped "unknown" status downstream.
        assert sim["data"]["envelopeSummary"]["status"] == "unknown"

    def test_connect_path_unaffected_by_navigator_signature_keys(self):
        """Connect SIM payloads must not be misrouted even if they also
        carry Navigator-looking keys (defensive)."""
        payload = {
            "Envelope Id": "should-be-ignored-when-data-is-present",
            "Agreement Type": "should-be-ignored-too",
            "data": {
                "envelopeSummary": {
                    "envelopeId": "real-env-id",
                    "status": "completed",
                    "recipients": {"signers": []},
                }
            },
        }
        result = normalize_envelope(payload)
        # The Connect wrapper wins — Navigator dispatch is skipped because
        # ``data`` is present.
        assert result.agreement.provider_envelope_id == "real-env-id"
