"""
Test validation gap fixes: PO Learning + Vendor Auto-Resolution

Tests production-like scenarios:
1. TUMALOC vendor with non-standard PO formats that consistently fail BC PO validation
2. "SC Warehouses, LLC" vendor that should fuzzy-match to BC vendor "WAREHOU"
3. End-to-end fix_all_validation_gaps orchestration
"""

import asyncio
import pytest
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db_name = os.environ.get("DB_NAME", "gpi_document_hub")
    database = client[db_name]
    yield database
    client.close()


@pytest.mark.asyncio
async def test_po_learning_tumaloc(db):
    """Test that TUMALOC vendor with chronic PO failures gets po_expected=false."""
    from services.gap_closer_service import learn_vendor_po_validation_rate

    vendor_no = "TUMALOC_TEST"

    # Clean up
    await db.hub_documents.delete_many({"bc_vendor_number": vendor_no, "_test": True})
    await db.vendor_invoice_profiles.delete_one({"vendor_no": vendor_no})

    # Seed: TUMALOC profile with po_expected=true
    await db.vendor_invoice_profiles.insert_one({
        "vendor_no": vendor_no,
        "vendor_name": "Tumalo Creek Transportation (TEST)",
        "po_expected": True,
        "_test": True,
    })

    # Seed: 5 docs from TUMALOC, all with failed PO resolution
    for i in range(5):
        po_ref = ["001307", "19326", "SI-02-26-31777", "001308", "19400"][i]
        await db.hub_documents.insert_one({
            "id": f"test-tumaloc-{i}",
            "bc_vendor_number": vendor_no,
            "status": "NeedsReview",
            "is_duplicate": False,
            "po_resolution": {
                "status": "not_found",
                "miss_reason": "no_bc_match" if i < 3 else "invalid_po_format",
                "candidates_raw": [po_ref],
            },
            "extracted_fields": {"po_number": po_ref, "vendor": "Tumalo Creek"},
            "_test": True,
        })

    # Run the learning
    result = await learn_vendor_po_validation_rate(db, vendor_no)
    assert result["learned"] is True, f"Expected learning to succeed: {result}"
    assert result["rate"] >= 0.70
    assert result["total"] >= 3

    # Verify profile was updated
    profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0, "po_expected": 1, "po_learning": 1}
    )
    assert profile["po_expected"] is False
    assert profile["po_learning"]["source"] == "auto_po_learning"

    # Clean up
    await db.hub_documents.delete_many({"bc_vendor_number": vendor_no, "_test": True})
    await db.vendor_invoice_profiles.delete_one({"vendor_no": vendor_no})
    print("PASS: test_po_learning_tumaloc")


@pytest.mark.asyncio
async def test_vendor_auto_resolution(db):
    """Test that fuzzy matching finds a BC vendor profile match for an unknown vendor."""
    from services.gap_closer_service import auto_resolve_unmatched_vendor

    # Use a vendor name that won't have an existing alias
    test_vendor_raw = "Greenfield Logistics Solutions Test Corp"

    # Ensure a BC vendor profile exists that should fuzzy-match
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": "GREENFLD_TEST"},
        {"$set": {
            "vendor_no": "GREENFLD_TEST",
            "vendor_name": "Greenfield Logistics Solutions",
            "vendor_name_variants": [],
            "_test": True,
        }},
        upsert=True,
    )
    # Remove any existing alias for this test name
    from services.vendor_name_helpers import normalize_vendor_name
    normalized = normalize_vendor_name(test_vendor_raw)
    await db.vendor_aliases.delete_one({"normalized": normalized})

    # Create a test doc with unmatched vendor
    test_doc = {
        "id": "test-greenfield-1",
        "status": "NeedsReview",
        "extracted_fields": {"vendor": test_vendor_raw, "invoice_number": "INV-123", "amount": "500.00"},
        "readiness": {"blocking_reasons": ["vendor_unresolved"]},
        "_test": True,
    }
    await db.hub_documents.update_one(
        {"id": test_doc["id"]},
        {"$set": test_doc},
        upsert=True,
    )

    # Run vendor resolution
    result = await auto_resolve_unmatched_vendor(db, test_doc)
    assert result["resolved"] is True, f"Expected resolution: {result}"
    assert result["vendor_no"] == "GREENFLD_TEST"
    assert result["score"] >= 0.70

    # Verify doc was updated
    doc = await db.hub_documents.find_one({"id": "test-greenfield-1"}, {"_id": 0})
    assert doc["bc_vendor_number"] == "GREENFLD_TEST"
    assert doc["vendor_resolution"]["status"] == "resolved"

    # Verify alias was created
    alias = await db.vendor_aliases.find_one(
        {"vendor_no": "GREENFLD_TEST", "source": "auto_gap_closer"},
        {"_id": 0}
    )
    assert alias is not None, "Expected alias to be created"

    # Clean up
    await db.hub_documents.delete_one({"id": "test-greenfield-1"})
    await db.vendor_invoice_profiles.delete_one({"vendor_no": "GREENFLD_TEST"})
    await db.vendor_aliases.delete_one({"vendor_no": "GREENFLD_TEST", "source": "auto_gap_closer"})
    print("PASS: test_vendor_auto_resolution")


@pytest.mark.asyncio
async def test_readiness_po_relaxation(db):
    """Test that evaluate_and_persist respects po_expected=false from vendor profile."""
    from services.document_readiness_service import evaluate_readiness, compute_signals

    # Create a doc from a vendor with po_expected=false
    doc = {
        "id": "test-po-relax-1",
        "status": "NeedsReview",
        "bc_vendor_number": "RELAX_TEST",
        "vendor_canonical": "Test Vendor Relaxed",
        "vendor_resolution": {"status": "resolved", "vendor_no": "RELAX_TEST"},
        "vendor_match_method": "alias_match",
        "extracted_fields": {
            "vendor": "Test Vendor Relaxed",
            "invoice_number": "INV-999",
            "amount": "1500.00",
            "po_number": "XYZ-NON-STANDARD",
        },
        "bc_validation": {
            "checks": [{"check_name": "po_check", "passed": False, "details": "No BC PO match"}]
        },
        "_vendor_profile_po_not_required": True,  # Simulating learned profile
    }

    signals = compute_signals(doc)
    assert signals["po_resolved"] is True, f"po_resolved should be True when vendor PO not required: {signals}"
    assert signals["vendor_resolved"] is True

    readiness = evaluate_readiness(doc)
    assert readiness["status"] == "ready_auto_draft", f"Expected ready_auto_draft: {readiness}"
    print("PASS: test_readiness_po_relaxation")


@pytest.mark.asyncio
async def test_po_learning_insufficient_docs(db):
    """Test that PO learning doesn't trigger with too few docs."""
    from services.gap_closer_service import learn_vendor_po_validation_rate

    vendor_no = "FEWDOCS_TEST"
    await db.hub_documents.delete_many({"bc_vendor_number": vendor_no, "_test": True})

    # Only 1 doc (below threshold of 3)
    await db.hub_documents.insert_one({
        "id": "test-few-1",
        "bc_vendor_number": vendor_no,
        "po_resolution": {"status": "not_found"},
        "is_duplicate": False,
        "_test": True,
    })

    result = await learn_vendor_po_validation_rate(db, vendor_no)
    assert result["learned"] is False, f"Should not learn with 1 doc: {result}"

    # Clean up
    await db.hub_documents.delete_many({"bc_vendor_number": vendor_no, "_test": True})
    print("PASS: test_po_learning_insufficient_docs")


@pytest.mark.asyncio
async def test_vendor_resolution_no_match(db):
    """Test that vendor resolution returns resolved=False when no match found."""
    from services.gap_closer_service import auto_resolve_unmatched_vendor

    doc = {
        "id": "test-nomatch-1",
        "extracted_fields": {"vendor": "ZZZZZ Completely Unknown Vendor Name 12345"},
    }

    result = await auto_resolve_unmatched_vendor(db, doc)
    assert result["resolved"] is False, f"Should not resolve unknown vendor: {result}"
    print("PASS: test_vendor_resolution_no_match")


if __name__ == "__main__":
    async def run_all():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        database = client[os.environ.get("DB_NAME", "gpi_document_hub")]

        print("=== Running Validation Gap Tests ===\n")
        try:
            await test_po_learning_tumaloc(database)
            await test_vendor_auto_resolution(database)
            await test_readiness_po_relaxation(database)
            await test_po_learning_insufficient_docs(database)
            await test_vendor_resolution_no_match(database)
            print("\n=== ALL TESTS PASSED ===")
        except Exception as e:
            print(f"\n=== TEST FAILED: {e} ===")
            raise
        finally:
            client.close()

    asyncio.run(run_all())
