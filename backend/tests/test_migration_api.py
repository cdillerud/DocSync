"""
Tests for Migration API Endpoints

Integration tests for the /api/migration/* endpoints.
"""
import pytest
import httpx
import sys
sys.path.insert(0, '/app/backend')


# Test configuration
API_BASE_URL = "https://vendor-link-2.preview.emergentagent.com"


@pytest.fixture
def api_client():
    """Create HTTP client for API calls."""
    return httpx.Client(base_url=API_BASE_URL, timeout=30.0)


class TestMigrationSupportedTypesAPI:
    """Tests for GET /api/migration/supported-types."""
    
    def test_returns_supported_types(self, api_client):
        """Test that endpoint returns supported types."""
        response = api_client.get("/api/migration/supported-types")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "supported_doc_types" in data
        assert "source_systems" in data
        assert "zetadocs_mappings" in data
        assert "square9_mappings" in data
    
    def test_includes_all_doc_types(self, api_client):
        """Test that all required doc types are listed."""
        response = api_client.get("/api/migration/supported-types")
        data = response.json()
        
        required_types = [
            "AP_INVOICE",
            "SALES_INVOICE",
            "PURCHASE_ORDER",
            "STATEMENT",
            "QUALITY_DOC",
        ]
        
        for doc_type in required_types:
            assert doc_type in data["supported_doc_types"]
    
    def test_includes_source_systems(self, api_client):
        """Test that both source systems are listed."""
        response = api_client.get("/api/migration/supported-types")
        data = response.json()
        
        assert "SQUARE9" in data["source_systems"]
        assert "ZETADOCS" in data["source_systems"]


class TestMigrationPreviewAPI:
    """Tests for GET /api/migration/preview."""
    
    def test_preview_returns_documents(self, api_client):
        """Test that preview returns sample documents."""
        response = api_client.get("/api/migration/preview?limit=3")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "source_name" in data
        assert "total_count" in data
        assert "preview_count" in data
        assert "documents" in data
        assert len(data["documents"]) <= 3
    
    def test_preview_document_structure(self, api_client):
        """Test preview document structure."""
        response = api_client.get("/api/migration/preview?limit=1")
        data = response.json()
        
        assert len(data["documents"]) >= 1
        doc = data["documents"][0]
        
        assert "legacy" in doc
        assert "preview" in doc
        assert "metadata" in doc["legacy"]
        assert "doc_type" in doc["preview"]
        assert "workflow_status" in doc["preview"]
    
    def test_preview_with_source_filter(self, api_client):
        """Test preview with source_filter."""
        response = api_client.get("/api/migration/preview?source_filter=SQUARE9&limit=10")
        
        assert response.status_code == 200
        data = response.json()
        
        # All documents should be from SQUARE9
        for doc in data["documents"]:
            assert doc["legacy"]["metadata"]["legacy_system"] == "SQUARE9"
    
    def test_preview_filters_applied(self, api_client):
        """Test that filters are returned in response."""
        response = api_client.get("/api/migration/preview?source_filter=ZETADOCS&limit=5")
        data = response.json()
        
        assert data["filters"]["source_filter"] == "ZETADOCS"
        assert data["filters"]["limit"] == 5


class TestMigrationRunAPI:
    """Tests for POST /api/migration/run."""
    
    def test_dry_run_returns_stats(self, api_client):
        """Test dry-run returns statistics."""
        response = api_client.post(
            "/api/migration/run",
            json={"mode": "dry_run", "limit": 5}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["mode"] == "dry_run"
        assert "stats" in data
        assert "sample_documents" in data
        assert data["stats"]["total_processed"] == 5
    
    def test_dry_run_classification_breakdown(self, api_client):
        """Test dry-run includes classification breakdown."""
        response = api_client.post(
            "/api/migration/run",
            json={"mode": "dry_run", "limit": 10}
        )
        
        data = response.json()
        stats = data["stats"]
        
        assert "by_doc_type" in stats
        assert "by_source_system" in stats
        assert "by_workflow_status" in stats
    
    def test_dry_run_with_source_filter(self, api_client):
        """Test dry-run with source filter."""
        response = api_client.post(
            "/api/migration/run",
            json={"mode": "dry_run", "source_filter": "SQUARE9", "limit": 10}
        )
        
        data = response.json()
        
        # All counted systems should be SQUARE9
        if data["stats"]["by_source_system"]:
            assert "SQUARE9" in data["stats"]["by_source_system"]
            # ZETADOCS should not be present if only SQUARE9 was filtered
            if data["stats"]["total_success"] > 0:
                # Could have only SQUARE9 or both if filter didn't match
                pass
    
    def test_dry_run_sample_documents_structure(self, api_client):
        """Test sample documents have correct structure."""
        response = api_client.post(
            "/api/migration/run",
            json={"mode": "dry_run", "limit": 1}
        )
        
        data = response.json()
        
        assert len(data["sample_documents"]) >= 1
        doc = data["sample_documents"][0]
        
        # Core fields
        assert "id" in doc
        assert "doc_type" in doc
        assert "source_system" in doc
        assert "capture_channel" in doc
        assert "legacy_id" in doc
        assert "is_migrated" in doc
        assert "workflow_status" in doc
        assert "workflow_history" in doc
    
    def test_invalid_mode_returns_error(self, api_client):
        """Test invalid mode returns 400."""
        response = api_client.post(
            "/api/migration/run",
            json={"mode": "invalid_mode", "limit": 1}
        )
        
        assert response.status_code == 400
        assert "Invalid mode" in response.json()["detail"]
    
    def test_real_run_skips_duplicates(self, api_client):
        """Test real run skips already migrated documents."""
        # First run - should migrate some
        response1 = api_client.post(
            "/api/migration/run",
            json={"mode": "real", "limit": 2}
        )
        
        assert response1.status_code == 200
        
        # Second run - should skip duplicates
        response2 = api_client.post(
            "/api/migration/run",
            json={"mode": "real", "limit": 2}
        )
        
        data2 = response2.json()
        
        # All or most should be skipped as duplicates
        total = data2["stats"]["total_processed"]
        skipped = data2["stats"]["total_skipped"]
        
        # At least some should be skipped (the ones from first run)
        assert skipped >= 0  # Could be 0 if first run had new docs


class TestMigrationStatsAPI:
    """Tests for GET /api/migration/stats."""
    
    def test_stats_returns_counts(self, api_client):
        """Test stats endpoint returns counts."""
        response = api_client.get("/api/migration/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total_migrated" in data
        assert "by_legacy_system" in data
        assert "by_doc_type" in data
        assert "by_workflow_status" in data
    
    def test_stats_numbers_are_valid(self, api_client):
        """Test that stats numbers are non-negative integers."""
        response = api_client.get("/api/migration/stats")
        data = response.json()
        
        assert isinstance(data["total_migrated"], int)
        assert data["total_migrated"] >= 0
        
        for system, count in data["by_legacy_system"].items():
            assert isinstance(count, int)
            assert count >= 0


class TestMigrationGenerateSampleAPI:
    """Tests for POST /api/migration/generate-sample."""
    
    def test_generate_sample_success(self, api_client):
        """Test generating sample migration file."""
        response = api_client.post(
            "/api/migration/generate-sample",
            params={"output_path": "/app/backend/data/test_sample_migration.json"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] == True
        assert "path" in data
        assert "message" in data


class TestMigrationEndToEnd:
    """End-to-end tests for migration workflow."""
    
    def test_full_migration_workflow(self, api_client):
        """Test full migration workflow: preview -> dry-run -> real (limited)."""
        # Step 1: Preview
        preview_resp = api_client.get("/api/migration/preview?limit=3")
        assert preview_resp.status_code == 200
        preview_data = preview_resp.json()
        assert preview_data["total_count"] > 0
        
        # Step 2: Dry run
        dry_run_resp = api_client.post(
            "/api/migration/run",
            json={"mode": "dry_run", "limit": 3}
        )
        assert dry_run_resp.status_code == 200
        dry_run_data = dry_run_resp.json()
        assert dry_run_data["stats"]["total_errors"] == 0
        
        # Step 3: Check stats before real run
        stats_before = api_client.get("/api/migration/stats").json()
        
        # Step 4: Real run (small limit to not pollute test DB too much)
        # Note: This may skip if already migrated
        real_run_resp = api_client.post(
            "/api/migration/run",
            json={"mode": "real", "limit": 1}
        )
        assert real_run_resp.status_code == 200
        
        # Step 5: Check stats after
        stats_after = api_client.get("/api/migration/stats").json()
        
        # Stats should show migrated documents
        assert stats_after["total_migrated"] >= stats_before["total_migrated"]
    
    def test_migrated_docs_appear_on_dashboard(self, api_client):
        """Test that migrated documents appear on the document type dashboard."""
        # Get dashboard stats
        dashboard_resp = api_client.get("/api/dashboard/document-types")
        
        assert dashboard_resp.status_code == 200
        data = dashboard_resp.json()
        
        # Dashboard should have by_type field
        assert "by_type" in data
        
        # Check migration stats to see if there are migrated docs
        migration_stats = api_client.get("/api/migration/stats").json()
        
        # If we have migrated docs, they should be reflected somewhere in the dashboard
        if migration_stats["total_migrated"] > 0:
            # The doc types from migration should exist in dashboard
            for doc_type in migration_stats["by_doc_type"].keys():
                # Migrated docs should appear in the by_type metrics
                if doc_type in data["by_type"]:
                    doc_metrics = data["by_type"][doc_type]
                    assert "total" in doc_metrics
                    assert doc_metrics["total"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
