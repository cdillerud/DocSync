"""Pytest for Lane C Step 7b — Reselling COW evidence enrichment.

Proves Option 1 as signed:
  1. `resale_context` attaches ONLY to `cow_so_wrong_customer` rows
  2. Attaches ONLY when at least one resale-authorization signal is present
  3. Block severity of `cow_so_wrong_customer` is UNCHANGED
  4. Existing COW ownership truth surface (classify_item_ownership,
     get_cp_item, cp_item_registry) is reused, not duplicated
  5. No new accessor paths, no new collections, no new routes
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import mongomock_motor
import pytest

from workflows.inventory import ownership


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_resell_{uuid.uuid4().hex[:8]}"]


async def _seed_cp_item(db, *, item_no, customer_no, base_item_no="BASE-X"):
    """Helper: seed a CP item via the canonical upsert path — no direct
    collection writes (single-truth-surface discipline)."""
    payload = ownership.CpItemCreate(
        item_no=item_no,
        customer_no=customer_no,
        base_item_no=base_item_no,
        canonical_location="WH-MAIN",
    )
    await ownership.upsert_cp_item(db, payload=payload, actor="tests@example.com")


def _sales_doc(
    *,
    customer_no: str,
    item_no: str,
    resale_signals: dict | None = None,
):
    ef: dict = {
        "customer_no": customer_no,
        "line_items": [{"item_no": item_no, "quantity": 1}],
    }
    if resale_signals:
        ef.update(resale_signals)
    return {
        "id": "doc-1",
        "doc_type": "SALES_ORDER",
        "extracted_fields": ef,
    }


# ===========================================================================
# 1. `resale_context` attaches to wrong-customer rows when signals present
# ===========================================================================

@pytest.mark.asyncio
class TestResaleContextAttachment:
    async def test_full_signal_set_attached(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-001-CPA", customer_no="CUST-A")
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-001-CPA",
            resale_signals={
                "resale_authorization_id": "AUTH-777",
                "resale_authorized_by": "alice@cust-a.com",
                "resale_authorization_date": "2026-04-22",
            },
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)

        assert len(evidence) == 1
        row = evidence[0]
        assert row["blocker_code"] == ownership.BLOCKER_CODE_SO_WRONG_CUSTOMER
        assert row["resale_context"] == {
            "resale_authorization_id": "AUTH-777",
            "resale_authorized_by": "alice@cust-a.com",
            "resale_authorization_date": "2026-04-22",
        }

    async def test_partial_signal_only_present_keys(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-002-CPB", customer_no="CUST-A")
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-002-CPB",
            resale_signals={"resale_authorization_id": "AUTH-123"},
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)

        assert len(evidence) == 1
        assert evidence[0]["resale_context"] == {
            "resale_authorization_id": "AUTH-123",
        }
        # Only present keys survive — no Nones.
        assert "resale_authorized_by" not in evidence[0]["resale_context"]
        assert "resale_authorization_date" not in evidence[0]["resale_context"]

    async def test_empty_string_signal_not_attached(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-003-CPC", customer_no="CUST-A")
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-003-CPC",
            resale_signals={
                "resale_authorization_id": "",
                "resale_authorized_by": "   ",
                "resale_authorization_date": None,
            },
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        assert len(evidence) == 1
        # All signals empty/whitespace/None → no resale_context attached.
        assert "resale_context" not in evidence[0]

    async def test_trimming_preserves_value(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-004-CPD", customer_no="CUST-A")
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-004-CPD",
            resale_signals={"resale_authorization_id": "   AUTH-555   "},
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        assert evidence[0]["resale_context"]["resale_authorization_id"] == "AUTH-555"


# ===========================================================================
# 2. resale_context ONLY on wrong-customer code — NOT on same-customer rows
# ===========================================================================

@pytest.mark.asyncio
class TestResaleContextScoping:
    async def test_same_customer_base_item_row_has_no_resale_context(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-005-CPE", customer_no="CUST-A")
        # SO is for CUST-A — same-customer case → cow_so_uses_base_item code.
        doc = _sales_doc(
            customer_no="CUST-A",
            item_no="CP-005-CPE",
            resale_signals={
                "resale_authorization_id": "AUTH-IGNORED",
                "resale_authorized_by": "bob@cust-a.com",
                "resale_authorization_date": "2026-04-22",
            },
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        assert len(evidence) == 1
        assert evidence[0]["blocker_code"] == ownership.BLOCKER_CODE_SO_BASE
        # Even though signals are present, this is NOT a wrong-customer row
        # → resale_context must NOT attach (scope preserved).
        assert "resale_context" not in evidence[0]

    async def test_unknown_cp_pattern_row_has_no_resale_context(self, mongo_db):
        # Unknown-pattern item (matches CP regex but not registered).
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="SOME-ITEM-CPZ",
            resale_signals={"resale_authorization_id": "AUTH-UNK"},
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        assert len(evidence) == 1
        assert evidence[0]["blocker_code"] == ownership.BLOCKER_CODE_SO_BASE
        assert "resale_context" not in evidence[0]

    async def test_no_signals_no_resale_context_on_wrong_customer(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-006-CPF", customer_no="CUST-A")
        doc = _sales_doc(customer_no="CUST-B", item_no="CP-006-CPF")
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        assert len(evidence) == 1
        assert evidence[0]["blocker_code"] == ownership.BLOCKER_CODE_SO_WRONG_CUSTOMER
        # Existing behavior preserved: no signals → no resale_context.
        assert "resale_context" not in evidence[0]


# ===========================================================================
# 3. Severity / enforcement unchanged
# ===========================================================================

@pytest.mark.asyncio
class TestSeverityUnchanged:
    async def test_wrong_customer_still_appends_block_code(self, mongo_db):
        await _seed_cp_item(mongo_db, item_no="CP-007-CPG", customer_no="CUST-A")
        doc = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-007-CPG",
            resale_signals={"resale_authorization_id": "AUTH-STILL-BLOCKS"},
        )
        evidence = await ownership.check_cow_so_uses_base_item(mongo_db, doc)
        readiness = {"blocking_reasons": [], "explanations": []}
        result = ownership.apply_cow_so_blocker_to_readiness(readiness, evidence)

        # Block CODE is appended (enforcement unchanged).
        assert ownership.BLOCKER_CODE_SO_WRONG_CUSTOMER in result["blocking_reasons"]
        # Evidence is persisted under cow_so_items (existing additive field).
        assert len(result["cow_so_items"]) == 1
        assert result["cow_so_items"][0]["blocker_code"] == (
            ownership.BLOCKER_CODE_SO_WRONG_CUSTOMER
        )
        # resale_context is carried through unchanged.
        assert result["cow_so_items"][0]["resale_context"] == {
            "resale_authorization_id": "AUTH-STILL-BLOCKS"
        }

    async def test_authorization_presence_does_not_downgrade_block(self, mongo_db):
        """Authorization presence MUST NOT convert a block into a warn or
        remove the blocker_code. This is the core invariant of Option 1."""
        await _seed_cp_item(mongo_db, item_no="CP-008-CPH", customer_no="CUST-A")

        # Case A: no auth signals
        doc_a = _sales_doc(customer_no="CUST-B", item_no="CP-008-CPH")
        evidence_a = await ownership.check_cow_so_uses_base_item(mongo_db, doc_a)
        readiness_a = ownership.apply_cow_so_blocker_to_readiness(
            {"blocking_reasons": [], "explanations": []}, evidence_a
        )

        # Case B: full auth signals
        doc_b = _sales_doc(
            customer_no="CUST-B",
            item_no="CP-008-CPH",
            resale_signals={
                "resale_authorization_id": "AUTH-B",
                "resale_authorized_by": "carol@cust-a.com",
                "resale_authorization_date": "2026-04-22",
            },
        )
        evidence_b = await ownership.check_cow_so_uses_base_item(mongo_db, doc_b)
        readiness_b = ownership.apply_cow_so_blocker_to_readiness(
            {"blocking_reasons": [], "explanations": []}, evidence_b
        )

        # Both must have the same blocker_code list.
        assert readiness_a["blocking_reasons"] == readiness_b["blocking_reasons"]
        assert (
            ownership.BLOCKER_CODE_SO_WRONG_CUSTOMER
            in readiness_b["blocking_reasons"]
        )


# ===========================================================================
# 4. Single-truth-surface discipline
# ===========================================================================

class TestSingleTruthSurface:
    def test_extractor_reads_only_from_extracted_fields(self):
        import inspect
        src = inspect.getsource(ownership._extract_resale_context)
        # Must read from extracted_fields exclusively.
        assert 'doc.get("extracted_fields")' in src
        # Must NOT touch cp_item_registry or classify_item_ownership
        # (it's documentary-only, orthogonal to ownership).
        assert "cp_item_registry" not in src
        assert "classify_item_ownership" not in src
        assert "get_cp_item" not in src

    def test_no_new_ownership_accessor_introduced(self):
        """The module must not sprout a second ownership-reading path for
        the resale-context feature."""
        import inspect
        src = inspect.getsource(ownership)
        # The three canonical accessors remain the sole ownership reads.
        assert "async def classify_item_ownership" in src
        assert "async def get_cp_item" in src
        # No "classify_resale_ownership" / "get_resale_item" drift.
        assert "classify_resale_ownership" not in src
        assert "get_resale_item" not in src
        assert "resale_item_registry" not in src

    def test_resale_signal_key_surface_is_exactly_three(self):
        """Lock the documented surface — guard against scope creep."""
        assert ownership._RESALE_SIGNAL_KEYS == (
            "resale_authorization_id",
            "resale_authorized_by",
            "resale_authorization_date",
        )
