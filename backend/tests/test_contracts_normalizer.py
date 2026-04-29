"""Phase 2 — Agreement normalizer fixture-driven tests.

Run:
    cd /app/backend && python -m pytest tests/test_contracts_normalizer.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.contracts.agreement_normalizer import normalize_envelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_completed_envelope_payload() -> dict:
    """Realistic Connect SIM JSON for an envelope-completed event."""
    return {
        "event": "envelope-completed",
        "apiVersion": "v2.1",
        "uri": "/api/v2.1/accounts/abc/envelopes/env-1234",
        "retryCount": 0,
        "configurationId": 11,
        "generatedDateTime": "2026-04-29T19:00:00.0000000Z",
        "data": {
            "accountId": "acct-xyz",
            "userId": "u-1",
            "envelopeId": "env-1234",
            "envelopeSummary": {
                "envelopeId": "env-1234",
                "status": "completed",
                "subject": "Master Services Agreement — Acme Co",
                "emailSubject": "Please sign your MSA",
                "createdDateTime": "2026-04-25T10:00:00Z",
                "sentDateTime": "2026-04-25T10:01:00Z",
                "deliveredDateTime": "2026-04-26T08:30:00Z",
                "completedDateTime": "2026-04-29T18:55:30Z",
                "expireDateTime": "2027-04-25T10:00:00Z",
                "sender": {
                    "userName": "Sue Sender",
                    "email": "sue@gamerpackaging.com",
                    "companyName": "GPI Hub",
                },
                "recipients": {
                    "signers": [
                        {
                            "recipientId": "1",
                            "name": "Alice Buyer",
                            "email": "alice@acme.com",
                            "companyName": "Acme Co",
                            "status": "completed",
                            "routingOrder": "1",
                            "sentDateTime": "2026-04-25T10:01:00Z",
                            "signedDateTime": "2026-04-29T18:55:30Z",
                        },
                    ],
                    "carbonCopies": [
                        {
                            "recipientId": "2",
                            "name": "Bob Cc",
                            "email": "bob@acme.com",
                            "status": "sent",
                            "routingOrder": "2",
                        },
                    ],
                },
                "envelopeDocuments": [
                    {"documentId": "1", "name": "MSA.pdf", "type": "content",
                     "pages": "12", "size": "204800"},
                    {"documentId": "2", "name": "Exhibit_A.pdf", "type": "content"},
                ],
                "customFields": {
                    "textCustomFields": [
                        {"name": "effective_date", "value": "2026-05-01"},
                        {"name": "term_length_months", "value": "24"},
                    ],
                    "listCustomFields": [
                        {"name": "governing_law", "value": "NY"},
                    ],
                },
                "formData": [
                    {"name": "auto_renew", "value": "yes"},
                    {"name": "line_1_item", "value": "WIDGET-100"},
                    {"name": "line_1_qty", "value": "1000"},
                    {"name": "line_1_price", "value": "$2.50"},
                    {"name": "line_1_uom", "value": "EA"},
                    {"name": "line_1_total", "value": "2,500.00"},
                    {"name": "line_2_item", "value": "WIDGET-200"},
                    {"name": "line_2_qty", "value": "500"},
                    {"name": "line_2_price", "value": "5.75"},
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestNormalizeCompleted:
    def test_agreement_basics(self):
        n = normalize_envelope(_make_completed_envelope_payload(), event_id="evt-1")
        a = n.agreement
        assert a.provider_envelope_id == "env-1234"
        assert a.status == "completed"
        assert a.title == "Master Services Agreement — Acme Co"
        assert a.email_subject == "Please sign your MSA"
        assert a.sender_name == "Sue Sender"
        assert a.sender_email == "sue@gamerpackaging.com"
        assert a.completed_at == datetime(2026, 4, 29, 18, 55, 30, tzinfo=timezone.utc)
        assert a.expires_at is not None
        assert a.last_event_id == "evt-1"

    def test_parties(self):
        n = normalize_envelope(_make_completed_envelope_payload())
        # 1 signer + 1 cc + 1 synthetic sender
        roles = [p.role for p in n.parties]
        assert roles.count("signer") == 1
        assert roles.count("carbon_copy") == 1
        assert roles.count("sender") == 1

        signer = next(p for p in n.parties if p.role == "signer")
        assert signer.name == "Alice Buyer"
        assert signer.email == "alice@acme.com"
        assert signer.organization == "Acme Co"
        assert signer.normalized_org == "acme co"
        assert signer.signing_status == "completed"
        assert signer.routing_order == 1
        assert signer.signed_at is not None

    def test_terms_from_custom_fields_and_form_data(self):
        n = normalize_envelope(_make_completed_envelope_payload())
        keys = {(t.term_key, t.source) for t in n.terms}
        assert ("effective_date", "custom_field") in keys
        assert ("term_length_months", "custom_field") in keys
        assert ("governing_law", "custom_field") in keys
        assert ("auto_renew", "form_data") in keys
        # Pricing tabs must NOT pollute terms
        for t in n.terms:
            assert "line_" not in t.term_key

    def test_pricing(self):
        n = normalize_envelope(_make_completed_envelope_payload())
        lines = sorted(n.pricing, key=lambda p: p.line_no)
        assert len(lines) == 2
        l1 = lines[0]
        assert l1.line_no == 1
        assert l1.item_label == "WIDGET-100"
        assert l1.quantity == 1000
        assert l1.unit_price == 2.5
        assert l1.line_total == 2500.0
        assert l1.uom == "EA"

        l2 = lines[1]
        assert l2.line_no == 2
        assert l2.item_label == "WIDGET-200"
        assert l2.quantity == 500
        assert l2.unit_price == 5.75
        # No total field provided for line 2
        assert l2.line_total is None

    def test_documents(self):
        n = normalize_envelope(_make_completed_envelope_payload())
        ids = sorted(d.provider_document_id for d in n.documents)
        assert ids == ["1", "2"]
        d1 = next(d for d in n.documents if d.provider_document_id == "1")
        assert d1.name == "MSA.pdf"
        assert d1.page_count == 12
        assert d1.size_bytes == 204800

    def test_counts_on_agreement(self):
        n = normalize_envelope(_make_completed_envelope_payload())
        assert n.agreement.party_count == len(n.parties)
        assert n.agreement.document_count == len(n.documents)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unknown_status_recorded_as_warning(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["status"] = "in-the-stratosphere"
        n = normalize_envelope(payload)
        assert n.agreement.status == "unknown"
        codes = [w["code"] for w in n.warnings]
        assert "unknown_envelope_status" in codes

    def test_missing_envelope_id_raises(self):
        with pytest.raises(ValueError):
            normalize_envelope({"event": "envelope-sent", "data": {}})

    def test_accepts_direct_envelope_summary(self):
        payload = _make_completed_envelope_payload()
        envelope_only = payload["data"]["envelopeSummary"]
        n = normalize_envelope(envelope_only)
        assert n.agreement.provider_envelope_id == "env-1234"
        assert n.agreement.status == "completed"

    def test_invalid_email_dropped(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["recipients"]["signers"][0]["email"] = "not-an-email"
        n = normalize_envelope(payload)
        signer = next(p for p in n.parties if p.role == "signer")
        assert signer.email is None

    def test_voided_status(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["status"] = "voided"
        payload["data"]["envelopeSummary"]["voidedDateTime"] = "2026-04-29T20:00:00Z"
        n = normalize_envelope(payload)
        assert n.agreement.status == "voided"
        assert n.agreement.voided_at is not None

    def test_empty_recipients_emits_no_parties_except_sender(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["recipients"] = {}
        n = normalize_envelope(payload)
        assert all(p.role == "sender" for p in n.parties)

    def test_pricing_missing_item_warns(self):
        payload = _make_completed_envelope_payload()
        # Strip line_1_item but keep other tabs
        payload["data"]["envelopeSummary"]["formData"] = [
            {"name": "line_1_qty", "value": "10"},
            {"name": "line_1_price", "value": "1.00"},
        ]
        n = normalize_envelope(payload)
        assert len(n.pricing) == 1
        assert n.pricing[0].item_label is None
        codes = [w["code"] for w in n.warnings]
        assert "pricing_missing_item" in codes

    def test_party_missing_email_warns(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["recipients"]["signers"][0]["email"] = None
        n = normalize_envelope(payload)
        codes = [w["code"] for w in n.warnings]
        assert "party_missing_email" in codes

    def test_microsecond_truncation(self):
        payload = _make_completed_envelope_payload()
        payload["data"]["envelopeSummary"]["completedDateTime"] = "2026-04-29T18:55:30.1234567Z"
        n = normalize_envelope(payload)
        assert n.agreement.completed_at is not None
        assert n.agreement.completed_at.tzinfo is not None
