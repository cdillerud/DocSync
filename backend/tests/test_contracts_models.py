"""Phase 1 — Pydantic model validation tests for the Contract Intelligence module.

These tests intentionally cover ONLY the additive Phase 1 surface:

  * /app/backend/models/contracts.py        — 10 Pydantic models + index decls
  * /app/backend/services/integrations/docusign_client.py
                                            — JWT scaffold + HMAC validator

Running:

    cd /app/backend && python -m pytest tests/test_contracts_models.py -q
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.contracts import (
    CONTRACTS_COLLECTIONS,
    CONTRACTS_INDEXES,
    Agreement,
    AgreementBCLink,
    AgreementDocument,
    AgreementEvent,
    AgreementException,
    AgreementMatchAudit,
    AgreementObligation,
    AgreementParty,
    AgreementPricing,
    AgreementTerm,
)


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

class TestAgreement:
    def test_minimal_valid(self):
        a = Agreement(provider_envelope_id="env-123")
        assert a.id and len(a.id) >= 32
        assert a.provider == "docusign"
        assert a.status == "unknown"
        assert a.provider_envelope_id == "env-123"
        assert a.created_at.tzinfo is not None
        assert a.updated_at.tzinfo is not None

    def test_envelope_id_required_nonempty(self):
        with pytest.raises(ValidationError):
            Agreement(provider_envelope_id="   ")
        with pytest.raises(ValidationError):
            Agreement(provider_envelope_id="")

    def test_status_constrained(self):
        for status in ("sent", "completed", "declined", "voided", "expired"):
            assert Agreement(provider_envelope_id="x", status=status).status == status
        with pytest.raises(ValidationError):
            Agreement(provider_envelope_id="x", status="bogus")

    def test_extras_ignored(self):
        a = Agreement(provider_envelope_id="x", _id="should-be-ignored", random="x")
        dumped = a.model_dump()
        assert "_id" not in dumped
        assert "random" not in dumped


# ---------------------------------------------------------------------------
# AgreementParty
# ---------------------------------------------------------------------------

class TestAgreementParty:
    def test_role_constrained(self):
        for role in ("signer", "carbon_copy", "sender", "approver"):
            p = AgreementParty(agreement_id="a1", role=role)
            assert p.role == role
        with pytest.raises(ValidationError):
            AgreementParty(agreement_id="a1", role="ceo")

    def test_email_validation(self):
        # valid
        AgreementParty(
            agreement_id="a1", role="signer", email="alice@example.com",
        )
        # invalid
        with pytest.raises(ValidationError):
            AgreementParty(agreement_id="a1", role="signer", email="not-an-email")

    def test_signing_status_default(self):
        p = AgreementParty(agreement_id="a1", role="signer")
        assert p.signing_status == "unknown"


# ---------------------------------------------------------------------------
# AgreementTerm / AgreementPricing / AgreementObligation
# ---------------------------------------------------------------------------

class TestTermPricingObligation:
    def test_term_key_nonempty(self):
        AgreementTerm(agreement_id="a1", term_key="effective_date")
        with pytest.raises(ValidationError):
            AgreementTerm(agreement_id="a1", term_key="  ")

    def test_term_confidence_bounds(self):
        AgreementTerm(agreement_id="a1", term_key="x", confidence=0.0)
        AgreementTerm(agreement_id="a1", term_key="x", confidence=1.0)
        with pytest.raises(ValidationError):
            AgreementTerm(agreement_id="a1", term_key="x", confidence=-0.1)
        with pytest.raises(ValidationError):
            AgreementTerm(agreement_id="a1", term_key="x", confidence=1.5)

    def test_pricing_match_method_optional(self):
        p = AgreementPricing(agreement_id="a1")
        assert p.match_method is None
        assert p.match_confidence == 0.0
        with pytest.raises(ValidationError):
            AgreementPricing(agreement_id="a1", match_method="not_a_method")

    def test_obligation_kind_constrained(self):
        for k in ("payment", "delivery", "renewal", "sla"):
            o = AgreementObligation(agreement_id="a1", kind=k, description="x")
            assert o.kind == k
        with pytest.raises(ValidationError):
            AgreementObligation(agreement_id="a1", kind="bogus", description="x")
        with pytest.raises(ValidationError):
            # description required
            AgreementObligation(agreement_id="a1", kind="payment")


# ---------------------------------------------------------------------------
# AgreementDocument
# ---------------------------------------------------------------------------

class TestAgreementDocument:
    def test_required_fields(self):
        d = AgreementDocument(agreement_id="a1", provider_document_id="doc-1")
        assert d.provider_document_id == "doc-1"
        with pytest.raises(ValidationError):
            AgreementDocument(agreement_id="a1")  # missing provider_document_id


# ---------------------------------------------------------------------------
# AgreementBCLink
# ---------------------------------------------------------------------------

class TestAgreementBCLink:
    def test_minimum_valid(self):
        link = AgreementBCLink(
            agreement_id="a1",
            link_type="customer",
            bc_entity="customers",
            bc_no="C-001",
        )
        assert link.status == "proposed"
        assert link.match_method == "unmatched"
        assert link.linked_by == "system"

    def test_link_type_constrained(self):
        with pytest.raises(ValidationError):
            AgreementBCLink(
                agreement_id="a1", link_type="zebra",
                bc_entity="customers", bc_no="C-1",
            )

    def test_match_method_set(self):
        link = AgreementBCLink(
            agreement_id="a1", link_type="vendor",
            bc_entity="vendors", bc_no="V-1",
            match_method="alias", confidence=0.87,
            status="confirmed", confirmed_by="user-42",
        )
        assert link.match_method == "alias"
        assert link.status == "confirmed"


# ---------------------------------------------------------------------------
# AgreementEvent — webhook idempotency surface
# ---------------------------------------------------------------------------

class TestAgreementEvent:
    def test_event_id_required(self):
        with pytest.raises(ValidationError):
            AgreementEvent(provider_event_id="", event_type="envelope-completed")
        with pytest.raises(ValidationError):
            AgreementEvent(provider_event_id="   ", event_type="envelope-completed")

    def test_default_unprocessed(self):
        e = AgreementEvent(
            provider_event_id="evt-1", event_type="envelope-completed",
            raw_payload={"envelopeId": "x"},
        )
        assert e.processed is False
        assert e.transport == "webhook"
        assert e.received_at.tzinfo is not None

    def test_idempotency_key_shape(self):
        """The (provider, provider_event_id) pair is the idempotency key.

        Verify that both fields exist on the model so the unique index
        declaration in CONTRACTS_INDEXES['agreement_events'] aligns with
        the actual schema fields.
        """
        e = AgreementEvent(provider_event_id="evt-1", event_type="any")
        dumped = e.model_dump()
        assert "provider" in dumped and "provider_event_id" in dumped
        # Index declares (provider, provider_event_id) unique
        idx = next(
            i for i in CONTRACTS_INDEXES["agreement_events"]
            if i.get("name") == "uniq_provider_event"
        )
        assert idx["unique"] is True
        assert idx["keys"] == [("provider", 1), ("provider_event_id", 1)]


# ---------------------------------------------------------------------------
# AgreementException / AgreementMatchAudit
# ---------------------------------------------------------------------------

class TestExceptionAndAudit:
    def test_exception_defaults(self):
        ex = AgreementException(agreement_id="a1", code="party_unmatched")
        assert ex.severity == "medium"
        assert ex.status == "open"
        assert ex.opened_at.tzinfo is not None

    def test_exception_code_constrained(self):
        with pytest.raises(ValidationError):
            AgreementException(agreement_id="a1", code="not_a_code")

    def test_audit_action_constrained(self):
        AgreementMatchAudit(agreement_id="a1", action="proposed_link")
        with pytest.raises(ValidationError):
            AgreementMatchAudit(agreement_id="a1", action="time_travel")

    def test_audit_actor_default_system(self):
        a = AgreementMatchAudit(agreement_id="a1", action="exception_resolved")
        assert a.actor == "system"


# ---------------------------------------------------------------------------
# Collection registry / index declaration shape
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_ten_collections_declared(self):
        assert len(CONTRACTS_COLLECTIONS) == 10
        expected = {
            "agreements", "agreement_parties", "agreement_terms",
            "agreement_pricing", "agreement_obligations",
            "agreement_documents", "agreement_bc_links",
            "agreement_events", "agreement_exceptions",
            "agreement_match_audit",
        }
        assert set(CONTRACTS_COLLECTIONS.keys()) == expected

    def test_indexes_declared_for_every_collection(self):
        # Every collection should have at least one index declared.
        for name in CONTRACTS_COLLECTIONS:
            assert name in CONTRACTS_INDEXES, f"{name} missing index spec"
            assert len(CONTRACTS_INDEXES[name]) >= 1

    def test_index_specs_have_required_keys(self):
        for name, specs in CONTRACTS_INDEXES.items():
            for spec in specs:
                assert "keys" in spec, f"{name}: missing keys"
                assert "name" in spec, f"{name}: missing name"
                assert isinstance(spec["keys"], list), f"{name}: keys must be list"
                for pair in spec["keys"]:
                    assert isinstance(pair, tuple) and len(pair) == 2

    def test_unique_indexes_present(self):
        # Critical uniqueness: envelopes are unique per provider, events too.
        agr = next(
            i for i in CONTRACTS_INDEXES["agreements"]
            if i.get("name") == "uniq_envelope"
        )
        assert agr["unique"] is True
        evt = next(
            i for i in CONTRACTS_INDEXES["agreement_events"]
            if i.get("name") == "uniq_provider_event"
        )
        assert evt["unique"] is True
