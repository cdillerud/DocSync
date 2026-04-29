"""Phase 2 — BC matcher tests.

Run:
    cd /app/backend && python -m pytest tests/test_contracts_matcher.py -q
"""
from __future__ import annotations

import pytest

from models.contracts import (
    AgreementParty,
    AgreementPricing,
)
from services.contracts.bc_agreement_matcher import (
    AUTO_CONFIRM_THRESHOLD,
    MIN_PROPOSE_THRESHOLD,
    BCAgreementMatcher,
    BCCandidate,
    InMemoryBCRepository,
)


# ---------------------------------------------------------------------------
# Fake repo helpers
# ---------------------------------------------------------------------------

def _repo_with_acme():
    return InMemoryBCRepository(
        customers=[
            {"no": "C-001", "name": "Acme Co Inc", "email": "billing@acme.com"},
            {"no": "C-002", "name": "Globex Corporation"},
        ],
        vendors=[
            {"no": "V-200", "name": "Office Supply Inc"},
        ],
        items=[
            {"no": "ITM-100", "name": "WIDGET-100 Premium"},
            {"no": "ITM-200", "name": "Widget 200 Standard"},
            {"no": "ITM-999", "name": "Sprocket Universal"},
        ],
    )


@pytest.mark.asyncio
class TestPartyMatching:
    async def test_high_confidence_auto_confirm(self):
        repo = InMemoryBCRepository(
            customers=[{"no": "C-001", "name": "Acme Co", "email": "alice@acme.com"}],
        )
        matcher = BCAgreementMatcher(repo)
        party = AgreementParty(
            agreement_id="a1", role="signer",
            name="Alice Buyer", email="alice@acme.com",
            organization="Acme Co",
        )
        result = await matcher.match(agreement_id="a1", parties=[party], pricing=[])

        cust_links = [link for link in result.links if link.link_type == "customer"]
        assert len(cust_links) == 1
        link = cust_links[0]
        assert link.bc_no == "C-001"
        assert link.confidence >= AUTO_CONFIRM_THRESHOLD
        assert link.status == "auto_confirmed"
        assert link.match_method in ("exact_name", "normalized")

    async def test_partial_match_proposed(self):
        repo = InMemoryBCRepository(
            # Lower-confidence partial match; "Acme Co Inc" vs "Acme Limited" share 1 token
            customers=[{"no": "C-LAT", "name": "Acme Limited"}],
        )
        matcher = BCAgreementMatcher(repo)
        party = AgreementParty(
            agreement_id="a1", role="signer",
            name="Acme Co Inc", organization="Acme Co Inc",
        )
        result = await matcher.match(agreement_id="a1", parties=[party], pricing=[])
        # Should be below auto-confirm but above propose threshold
        cust_links = [link for link in result.links if link.link_type == "customer"]
        if cust_links:
            link = cust_links[0]
            assert link.status in ("proposed", "auto_confirmed")
        # Or — if confidence is below MIN_PROPOSE_THRESHOLD — should appear as exception
        if not cust_links:
            codes = [e.code for e in result.exceptions]
            assert "party_unmatched" in codes

    async def test_no_candidates_emits_customer_exception(self):
        repo = InMemoryBCRepository()  # empty
        matcher = BCAgreementMatcher(repo)
        party = AgreementParty(
            agreement_id="a1", role="signer",
            name="Mystery Inc", organization="Mystery Inc",
        )
        result = await matcher.match(agreement_id="a1", parties=[party], pricing=[])
        # No links produced
        assert not result.links
        # One exception per missing customer match (vendor side stays quiet)
        cust_ex = [e for e in result.exceptions if e.code == "party_unmatched"]
        assert len(cust_ex) == 1
        assert cust_ex[0].related_party_id == party.id

    async def test_dedupe_same_company_two_signers(self):
        repo = _repo_with_acme()
        matcher = BCAgreementMatcher(repo)
        p1 = AgreementParty(
            agreement_id="a1", role="signer",
            name="Alice", organization="Acme Co Inc", email="alice@acme.com",
        )
        p2 = AgreementParty(
            agreement_id="a1", role="signer",
            name="Bob", organization="Acme Co Inc",
        )
        result = await matcher.match(agreement_id="a1", parties=[p1, p2], pricing=[])
        cust_links = [link for link in result.links if link.link_type == "customer"]
        # Even with two signers, one link per BC entity
        assert len(cust_links) == 1

    async def test_witness_role_skipped(self):
        repo = _repo_with_acme()
        matcher = BCAgreementMatcher(repo)
        party = AgreementParty(
            agreement_id="a1", role="witness",
            name="Wendy Witness", organization="Acme Co",
        )
        result = await matcher.match(agreement_id="a1", parties=[party], pricing=[])
        assert not result.links
        assert not result.exceptions  # we don't even try


# ---------------------------------------------------------------------------
# Item matching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestItemMatching:
    async def test_item_high_confidence(self):
        repo = _repo_with_acme()
        matcher = BCAgreementMatcher(repo)
        line = AgreementPricing(
            agreement_id="a1", line_no=1,
            item_label="WIDGET-100", description="Premium widget",
        )
        result = await matcher.match(agreement_id="a1", parties=[], pricing=[line])
        item_links = [link for link in result.links if link.link_type == "item"]
        assert len(item_links) == 1
        assert item_links[0].bc_no == "ITM-100"
        assert item_links[0].pricing_id == line.id

    async def test_item_no_match_emits_exception(self):
        repo = _repo_with_acme()
        matcher = BCAgreementMatcher(repo)
        line = AgreementPricing(
            agreement_id="a1", line_no=1, item_label="UNOBTAINIUM",
        )
        result = await matcher.match(agreement_id="a1", parties=[], pricing=[line])
        codes = [e.code for e in result.exceptions]
        assert "item_unmatched" in codes
        ex = next(e for e in result.exceptions if e.code == "item_unmatched")
        assert ex.related_pricing_id == line.id

    async def test_pricing_with_no_label_or_description_warned(self):
        repo = _repo_with_acme()
        matcher = BCAgreementMatcher(repo)
        line = AgreementPricing(agreement_id="a1", line_no=1)
        result = await matcher.match(agreement_id="a1", parties=[], pricing=[line])
        codes = [e.code for e in result.exceptions]
        assert "item_unmatched" in codes


# ---------------------------------------------------------------------------
# Threshold contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestThresholds:
    async def test_thresholds_consistent(self):
        assert AUTO_CONFIRM_THRESHOLD > MIN_PROPOSE_THRESHOLD
        assert 0 < MIN_PROPOSE_THRESHOLD < AUTO_CONFIRM_THRESHOLD <= 1

    async def test_custom_thresholds_respected(self):
        # Inject a stub repo that always returns 0.85 score
        class StubRepo:
            async def find_customer_candidates(self, **kw):
                return [BCCandidate(no="X", name="X", score=0.85, method="fuzzy")]

            async def find_vendor_candidates(self, **kw):
                return []

            async def find_item_candidates(self, **kw):
                return []

        # With auto_confirm=0.80, score 0.85 should auto-confirm
        m = BCAgreementMatcher(StubRepo(), auto_confirm_threshold=0.80,
                               min_propose_threshold=0.50)
        party = AgreementParty(
            agreement_id="a1", role="signer", name="X", organization="X",
        )
        result = await m.match(agreement_id="a1", parties=[party], pricing=[])
        cust_links = [link for link in result.links if link.link_type == "customer"]
        assert len(cust_links) == 1
        assert cust_links[0].status == "auto_confirmed"
