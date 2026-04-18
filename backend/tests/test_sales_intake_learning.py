"""
Tests for sales_intake_learning_service — the hub-wide Giovanni-pattern
BC learning orchestrator.

Covers:
  • Customer resolution priority (bc_prod_validation > matched_customer_no > name-only)
  • Cold-start detection + transparent reason message
  • Lazy BC pattern seeding when no existing pattern
  • Quantity bounds violation surfaces on the doc
  • Actionable findings flag
  • XLS staging adapter
  • Backfill helper
  • Summary aggregation shape
"""

import asyncio
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock


@pytest.fixture
def giovanni_doc():
    """A sample hub_document mimicking Nikki's monthly Giovanni blanket PO."""
    return {
        "id": str(uuid.uuid4()),
        "doc_type": "purchase_order",
        "file_name": "Giovanni_PO_61312.pdf",
        "extracted_fields": {
            "customer": "Giovanni Food Company., Inc.",
            "line_items": [
                {
                    "item_no": "C-9874-10001833",
                    "description": "24oz Jar",
                    "quantity": 60,
                    "unit_price": 0.85,
                },
                {
                    "item_no": "OIPALLET",
                    "description": "OI Pallet",
                    "quantity": 20,
                    "unit_price": 0,
                },
            ],
        },
        "bc_prod_validation": {
            "customer_match": {
                "found": True,
                "bc_customer_no": "C-10250",
                "bc_customer_name": "Giovanni Food Co., Inc.",
            },
        },
    }


@pytest.mark.asyncio
async def test_intake_learning_giovanni_happy_path(giovanni_doc):
    """Full orchestrator run against a mocked Giovanni document + pattern store."""
    from services import sales_intake_learning_service as sils

    doc_id = giovanni_doc["id"]

    # ── Mock DB ──
    # hub_documents.find_one returns our sample; update_one is no-op
    # order_line_patterns.count_documents returns 1 (pretend we already learned)
    # bc_reference_cache.find_one returns None (items not in catalog to simulate unmatched)
    mock_db = AsyncMock()
    mock_db.hub_documents = AsyncMock()
    mock_db.hub_documents.find_one = AsyncMock(return_value=giovanni_doc)
    mock_db.hub_documents.update_one = AsyncMock()
    mock_db.order_line_patterns = AsyncMock()
    mock_db.order_line_patterns.count_documents = AsyncMock(return_value=1)
    mock_db.bc_reference_cache = AsyncMock()
    mock_db.bc_reference_cache.find_one = AsyncMock(return_value=None)

    # Mock the learning helpers to avoid touching actual BC history
    with patch("services.order_line_patterns.get_suggested_lines",
               new=AsyncMock(return_value=[{
                   "line_type": "Item", "item_no": "OITIERSHEET",
                   "description": "OI Tier Sheet", "quantity": 4,
                   "source": "learned_pattern", "confidence": 0.93,
                   "occurrences": 12, "frequency": 0.9,
               }])), \
         patch("services.order_line_patterns.check_quantity_bounds",
               new=AsyncMock(return_value={
                   "in_bounds": False,
                   "violations": [{
                       "item_no": "C-9874-10001833",
                       "po_quantity": 60, "expected_min": 24.5,
                       "expected_max": 99.4, "mean": 61.9, "std_dev": 18.7,
                       "sample_count": 5, "deviation_factor": 0.1,
                       "severity": "warning",
                   }],
               })):
        result = await sils.run_intake_learning(doc_id, db=mock_db)

    assert result["customer_no"] == "C-10250"
    assert result["customer_source"] == "bc_prod_validation"
    assert result["line_count"] == 2
    assert result["patterns_available"] == 1
    assert result["cold_start"] is False
    assert len(result["suggested_lines"]) == 1
    assert result["suggested_lines"][0]["item_no"] == "OITIERSHEET"
    assert result["bounds_check"]["in_bounds"] is False
    assert len(result["bounds_check"]["violations"]) == 1
    assert result["item_validation"]["lines_unmatched"] == 2
    assert result["has_actionable_findings"] is True
    # stages_ran should include suggested_lines + bounds_check + item_catalog
    assert "suggested_lines" in result["stages_ran"]
    assert "bounds_check" in result["stages_ran"]
    assert "item_catalog" in result["stages_ran"]


@pytest.mark.asyncio
async def test_intake_learning_cold_start_with_customer_name_only():
    """Customer extracted but not resolved → cold_start=True with transparent reason."""
    from services import sales_intake_learning_service as sils
    doc_id = str(uuid.uuid4())
    doc = {
        "id": doc_id,
        "doc_type": "purchase_order",
        "extracted_fields": {"customer": "Brand New Customer Co."},
    }
    mock_db = AsyncMock()
    mock_db.hub_documents = AsyncMock()
    mock_db.hub_documents.find_one = AsyncMock(return_value=doc)
    mock_db.hub_documents.update_one = AsyncMock()

    result = await sils.run_intake_learning(doc_id, db=mock_db)
    assert result["cold_start"] is True
    assert "no BC customer_no" in result["cold_start_reason"]
    assert result["customer_name"] == "Brand New Customer Co."
    assert result["patterns_available"] == 0


@pytest.mark.asyncio
async def test_intake_learning_skipped_for_non_scope_doc():
    """Random doc types are skipped cleanly with an explicit reason."""
    from services import sales_intake_learning_service as sils
    doc_id = str(uuid.uuid4())
    doc = {
        "id": doc_id,
        "doc_type": "Other",
        "extracted_fields": {},
    }
    mock_db = AsyncMock()
    mock_db.hub_documents = AsyncMock()
    mock_db.hub_documents.find_one = AsyncMock(return_value=doc)
    mock_db.hub_documents.update_one = AsyncMock()
    result = await sils.run_intake_learning(doc_id, db=mock_db)
    assert result.get("skipped") is True
    assert "not in learning scope" in result.get("skip_reason", "")


@pytest.mark.asyncio
async def test_sales_invoice_is_in_scope():
    """GPI's ZD00010 SALES_INVOICE (blanket sales order) must be learned, not skipped."""
    from services import sales_intake_learning_service as sils
    doc_id = str(uuid.uuid4())
    doc = {
        "id": doc_id,
        "doc_type": "SALES_INVOICE",
        "extracted_fields": {"customer": "Giovanni Food Co."},
    }
    mock_db = AsyncMock()
    mock_db.hub_documents = AsyncMock()
    mock_db.hub_documents.find_one = AsyncMock(return_value=doc)
    mock_db.hub_documents.update_one = AsyncMock()
    result = await sils.run_intake_learning(doc_id, db=mock_db)
    assert result.get("skipped") is not True
    assert result.get("cold_start") is True


@pytest.mark.asyncio
async def test_xls_staging_intake_learning_cold_start():
    """XLS staging with assigned customer but no BC posted orders = cold_start."""
    from services import sales_intake_learning_service as sils
    staging_id = str(uuid.uuid4())
    customer_workspace_id = str(uuid.uuid4())
    staging = {
        "id": staging_id,
        "assigned_customer_id": customer_workspace_id,
        "rows": [
            {"item": "WIDGET-A", "item_description": "Widget A", "qty": 100, "uom": "EA"},
        ],
    }
    mock_db = AsyncMock()
    mock_db.__getitem__ = lambda self, name: AsyncMock(
        find_one=AsyncMock(return_value=(
            staging if "staging" in name else
            {"code": "ACME", "name": "Acme Inc.", "bc_customer_no": "C-20001"}
        )),
        update_one=AsyncMock(),
    )
    mock_db.order_line_patterns = AsyncMock()
    mock_db.order_line_patterns.count_documents = AsyncMock(return_value=0)
    mock_db.bc_reference_cache = AsyncMock()
    mock_db.bc_reference_cache.find_one = AsyncMock(return_value=None)

    with patch("services.order_line_patterns.learn_from_bc_posted_orders",
               new=AsyncMock(return_value={"patterns_learned": 0, "customer_patterns": []})):
        result = await sils.run_intake_learning_for_xls_staging(staging_id, db=mock_db)

    assert result["scope"] == "inventory_xls_staging"
    assert result["customer_no"] == "C-20001"
    assert result["cold_start"] is True
    assert result["patterns_available"] == 0
    assert result["line_count"] == 1


@pytest.mark.asyncio
async def test_summary_shape_keys():
    """The summary endpoint returns a stable shape the dashboard can bind to."""
    from services import sales_intake_learning_service as sils

    # Minimal in-memory fake db
    class FakeColl:
        def __init__(self, docs):
            self.docs = docs
        async def count_documents(self, q):
            return len(self.docs)
        def aggregate(self, pipeline):
            async def _gen():
                for _ in []:
                    yield _
            return _gen()

    class FakeDb:
        hub_documents = FakeColl([])
        def __getitem__(self, name):
            return FakeColl([])

    res = await sils.get_intake_learning_summary(db=FakeDb())
    for k in ("generated_at", "hub", "xls_staging", "top_customers"):
        assert k in res
    for k in ("eligible_docs", "with_insights", "cold_start", "actionable_findings",
              "bounds_violations", "coverage_pct"):
        assert k in res["hub"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
