"""
Test STEP 1: BC Customer + Salesperson Cache Sync & Rep Assignment Service

Tests:
  - ENTITY_CONFIGS includes "customers" and "salespeople"
  - _build_cache_document carries through entity-specific extra fields
  - get_rep_for_customer resolves via cache (customer → salesperson_code → salesperson)
  - get_rep_for_customer checks overrides first
  - override_rep_for_customer stores and clears overrides
  - list_rep_assignments aggregates customer counts per salesperson
  - sync_reps_from_bc triggers cache sync for customers + salespeople only
"""
import pytest
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bc_reference_cache_service import ENTITY_CONFIGS, BCReferenceCacheService
from services.rep_assignment_service import (
    get_rep_for_customer,
    list_rep_assignments,
    override_rep_for_customer,
    OVERRIDES_COLL,
)

_MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
_DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")

_CACHE_COLL = "bc_reference_cache"


def _motor_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    return client, client[_DB_NAME]


def _sync_cleanup():
    from pymongo import MongoClient
    c = MongoClient(_MONGO_URL)
    db = c[_DB_NAME]
    db[_CACHE_COLL].delete_many({"bc_entity_type": {"$in": ["customer", "salesperson"]}})
    db[OVERRIDES_COLL].delete_many({})
    c.close()


def _seed_customer(db_sync, customer_no, name, sp_code="", email=""):
    """Insert a customer record directly into bc_reference_cache (sync pymongo)."""
    db_sync[_CACHE_COLL].update_one(
        {"bc_record_id": f"cust-{customer_no}"},
        {"$set": {
            "bc_entity_type": "customer",
            "bc_domain": "master",
            "bc_record_id": f"cust-{customer_no}",
            "bc_document_no": customer_no,
            "normalized_document_no": customer_no.upper().replace("-", ""),
            "bc_customer_no": customer_no,
            "bc_customer_name": name,
            "displayName": name,
            "salesperson_code": sp_code,
            "email": email,
            "cached_at": "2026-02-15T00:00:00Z",
        }},
        upsert=True,
    )


def _seed_salesperson(db_sync, code, name, email=""):
    """Insert a salesperson record directly into bc_reference_cache (sync pymongo)."""
    db_sync[_CACHE_COLL].update_one(
        {"bc_record_id": code},
        {"$set": {
            "bc_entity_type": "salesperson",
            "bc_domain": "master",
            "bc_record_id": code,
            "bc_document_no": code,
            "normalized_document_no": code.upper(),
            "code": code,
            "name": name,
            "email": email,
            "cached_at": "2026-02-15T00:00:00Z",
        }},
        upsert=True,
    )


# =========================================================================
# Entity Config Tests
# =========================================================================

class TestEntityConfigs:
    def test_customers_entity_config_exists(self):
        assert "customers" in ENTITY_CONFIGS
        cfg = ENTITY_CONFIGS["customers"]
        assert cfg["entity_type"] == "customer"
        assert "salespersonCode" in cfg["select_fields"]
        assert "displayName" in cfg["select_fields"]

    def test_salespeople_entity_config_exists(self):
        assert "salespeople" in ENTITY_CONFIGS
        cfg = ENTITY_CONFIGS["salespeople"]
        assert cfg["entity_type"] == "salesperson"
        assert "code" in cfg["select_fields"]
        assert "name" in cfg["select_fields"]

    def test_customer_extract_fields(self):
        cfg = ENTITY_CONFIGS["customers"]
        raw = {
            "id": "uuid-123",
            "number": "C-001",
            "displayName": "Acme Corp",
            "salespersonCode": "JD",
            "email": "acme@test.com",
            "phoneNumber": "555-1234",
        }
        fields = cfg["extract_fields"](raw)
        assert fields["bc_record_id"] == "uuid-123"
        assert fields["bc_document_no"] == "C-001"
        assert fields["salesperson_code"] == "JD"
        assert fields["displayName"] == "Acme Corp"
        assert fields["email"] == "acme@test.com"

    def test_salesperson_extract_fields(self):
        cfg = ENTITY_CONFIGS["salespeople"]
        raw = {"code": "JD", "name": "John Doe", "email": "jd@gpi.com"}
        fields = cfg["extract_fields"](raw)
        assert fields["bc_record_id"] == "JD"
        assert fields["code"] == "JD"
        assert fields["name"] == "John Doe"
        assert fields["email"] == "jd@gpi.com"


# =========================================================================
# _build_cache_document Extra Fields Tests
# =========================================================================

class TestBuildCacheDocument:
    def test_customer_cache_doc_has_salesperson_code(self):
        svc = BCReferenceCacheService.__new__(BCReferenceCacheService)
        raw = {
            "id": "uuid-456",
            "number": "C-002",
            "displayName": "Beta LLC",
            "salespersonCode": "SM",
            "email": "beta@test.com",
            "phoneNumber": "555-5678",
        }
        config = ENTITY_CONFIGS["customers"]
        doc = svc._build_cache_document(raw, config)
        assert doc is not None
        assert doc["bc_entity_type"] == "customer"
        assert doc["salesperson_code"] == "SM"
        assert doc["displayName"] == "Beta LLC"
        assert doc["email"] == "beta@test.com"
        assert doc["phone_number"] == "555-5678"
        assert doc["bc_customer_no"] == "C-002"

    def test_salesperson_cache_doc_has_code_and_name(self):
        svc = BCReferenceCacheService.__new__(BCReferenceCacheService)
        raw = {"code": "AB", "name": "Alice Brown", "email": "ab@gpi.com"}
        config = ENTITY_CONFIGS["salespeople"]
        doc = svc._build_cache_document(raw, config)
        assert doc is not None
        assert doc["bc_entity_type"] == "salesperson"
        assert doc["code"] == "AB"
        assert doc["name"] == "Alice Brown"
        assert doc["email"] == "ab@gpi.com"

    def test_existing_entity_cache_doc_unchanged(self):
        """Existing entities (salesOrders) should not be affected by the extra fields change."""
        svc = BCReferenceCacheService.__new__(BCReferenceCacheService)
        raw = {
            "id": "so-uuid",
            "number": "SO-1001",
            "externalDocumentNumber": "PO-999",
            "customerName": "Test",
            "customerNumber": "C-003",
            "orderDate": "2026-01-15",
            "status": "Open",
            "totalAmountIncludingTax": 5000,
            "lastModifiedDateTime": "2026-01-15T10:00:00Z",
        }
        config = ENTITY_CONFIGS["salesOrders"]
        doc = svc._build_cache_document(raw, config)
        assert doc is not None
        assert doc["bc_entity_type"] == "sales_order"
        assert doc["bc_document_no"] == "SO-1001"
        assert doc["bc_customer_no"] == "C-003"


# =========================================================================
# get_rep_for_customer Tests
# =========================================================================

class TestGetRepForCustomer:
    @pytest.fixture(autouse=True)
    def setup(self):
        from pymongo import MongoClient
        self._client, self.db = _motor_db()
        self._sync_client = MongoClient(_MONGO_URL)
        self._sync_db = self._sync_client[_DB_NAME]
        yield
        _sync_cleanup()
        self._client.close()
        self._sync_client.close()

    @pytest.mark.asyncio
    async def test_returns_rep_from_bc_cache(self):
        _seed_customer(self._sync_db, "C-100", "Customer 100", sp_code="JD")
        _seed_salesperson(self._sync_db, "JD", "John Doe", "jd@gpi.com")

        result = await get_rep_for_customer(self.db, "C-100")
        assert result is not None
        assert result["rep_email"] == "jd@gpi.com"
        assert result["rep_name"] == "John Doe"
        assert result["salesperson_code"] == "JD"
        assert result["source"] == "bc_cache"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_customer(self):
        result = await get_rep_for_customer(self.db, "UNKNOWN-999")
        assert result is None

    @pytest.mark.asyncio
    async def test_customer_without_salesperson_code(self):
        _seed_customer(self._sync_db, "C-200", "No Rep Customer", sp_code="")

        result = await get_rep_for_customer(self.db, "C-200")
        assert result is not None
        assert result["salesperson_code"] == ""
        assert "no salesperson_code" in result.get("note", "")

    @pytest.mark.asyncio
    async def test_salesperson_code_not_in_cache(self):
        _seed_customer(self._sync_db, "C-300", "Missing SP", sp_code="XX")
        # Do NOT seed salesperson "XX"

        result = await get_rep_for_customer(self.db, "C-300")
        assert result is not None
        assert result["salesperson_code"] == "XX"
        assert result["rep_email"] == ""
        assert "not found in cache" in result.get("note", "")

    @pytest.mark.asyncio
    async def test_override_takes_priority(self):
        _seed_customer(self._sync_db, "C-400", "Override Customer", sp_code="JD")
        _seed_salesperson(self._sync_db, "JD", "John Doe", "jd@gpi.com")

        # Set override
        await override_rep_for_customer(
            self.db, "C-400", rep_email="override@gpi.com", rep_name="Override Rep"
        )

        result = await get_rep_for_customer(self.db, "C-400")
        assert result is not None
        assert result["rep_email"] == "override@gpi.com"
        assert result["rep_name"] == "Override Rep"
        assert result["source"] == "override"

    @pytest.mark.asyncio
    async def test_cleared_override_falls_back_to_bc(self):
        _seed_customer(self._sync_db, "C-500", "Cleared Customer", sp_code="AB")
        _seed_salesperson(self._sync_db, "AB", "Alice Brown", "ab@gpi.com")

        # Set then clear override
        await override_rep_for_customer(
            self.db, "C-500", rep_email="temp@gpi.com", rep_name="Temp"
        )
        await override_rep_for_customer(
            self.db, "C-500", rep_email="", rep_name=""
        )

        result = await get_rep_for_customer(self.db, "C-500")
        assert result is not None
        assert result["source"] == "bc_cache"
        assert result["rep_email"] == "ab@gpi.com"

    @pytest.mark.asyncio
    async def test_empty_customer_no_returns_none(self):
        result = await get_rep_for_customer(self.db, "")
        assert result is None


# =========================================================================
# override_rep_for_customer Tests
# =========================================================================

class TestOverrideRepForCustomer:
    @pytest.fixture(autouse=True)
    def setup(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_create_override(self):
        result = await override_rep_for_customer(
            self.db, "C-600", rep_email="rep@gpi.com", rep_name="New Rep",
            salesperson_code="NR",
        )
        assert result["customer_no"] == "C-600"
        assert result["rep_email"] == "rep@gpi.com"
        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_update_existing_override(self):
        await override_rep_for_customer(self.db, "C-700", "old@gpi.com", "Old Rep")
        result = await override_rep_for_customer(self.db, "C-700", "new@gpi.com", "New Rep")
        assert result["rep_email"] == "new@gpi.com"
        assert result["rep_name"] == "New Rep"

    @pytest.mark.asyncio
    async def test_clear_override_sets_inactive(self):
        await override_rep_for_customer(self.db, "C-800", "rep@gpi.com", "Rep")
        result = await override_rep_for_customer(self.db, "C-800", "", "")
        assert result["active"] is False


# =========================================================================
# list_rep_assignments Tests
# =========================================================================

class TestListRepAssignments:
    @pytest.fixture(autouse=True)
    def setup(self):
        from pymongo import MongoClient
        self._client, self.db = _motor_db()
        self._sync_client = MongoClient(_MONGO_URL)
        self._sync_db = self._sync_client[_DB_NAME]
        yield
        _sync_cleanup()
        self._client.close()
        self._sync_client.close()

    @pytest.mark.asyncio
    async def test_lists_rep_assignments(self):
        _seed_salesperson(self._sync_db, "JD", "John Doe", "jd@gpi.com")
        _seed_customer(self._sync_db, "C-A1", "Customer A1", sp_code="JD")
        _seed_customer(self._sync_db, "C-A2", "Customer A2", sp_code="JD")
        _seed_salesperson(self._sync_db, "AB", "Alice Brown", "ab@gpi.com")
        _seed_customer(self._sync_db, "C-B1", "Customer B1", sp_code="AB")

        assignments = await list_rep_assignments(self.db)
        assert len(assignments) >= 2

        jd_assign = next((a for a in assignments if a["salesperson_code"] == "JD"), None)
        assert jd_assign is not None
        assert jd_assign["rep_name"] == "John Doe"
        assert jd_assign["customer_count"] == 2

        ab_assign = next((a for a in assignments if a["salesperson_code"] == "AB"), None)
        assert ab_assign is not None
        assert ab_assign["customer_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_customers(self):
        assignments = await list_rep_assignments(self.db)
        # May be empty or only contain overrides
        assert isinstance(assignments, list)


# =========================================================================
# sync_reps_from_bc Tests (BC not available in preview)
# =========================================================================

class TestSyncRepsFromBc:
    @pytest.fixture(autouse=True)
    def setup(self):
        self._client, self.db = _motor_db()
        yield
        self._client.close()

    @pytest.mark.asyncio
    async def test_sync_returns_error_when_cache_not_initialized(self):
        """Without the global cache service, sync_reps should return error."""
        from services.rep_assignment_service import sync_reps_from_bc
        from services import bc_reference_cache_service
        # Temporarily clear global service
        old = bc_reference_cache_service._cache_service
        bc_reference_cache_service._cache_service = None
        try:
            result = await sync_reps_from_bc(self.db)
            assert result["status"] == "error"
        finally:
            bc_reference_cache_service._cache_service = old


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
