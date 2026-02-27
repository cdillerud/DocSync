"""
GPI Document Hub - Spiro Integration Tests

Tests for Spiro API client, sync service, and context generator.
Uses mocked API responses to avoid hitting real Spiro endpoints.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import modules under test
from services.spiro.spiro_client import (
    SpiroClient, SpiroTokenManager, normalize_company_name,
    is_spiro_enabled
)
from services.spiro.spiro_sync import (
    SpiroSyncService, transform_contact, transform_company, transform_opportunity
)
from services.spiro.spiro_context import (
    SpiroContextGenerator, SpiroContext, calculate_name_similarity,
    extract_email_domain, normalize_phone
)


# =============================================================================
# MOCK DATA
# =============================================================================

MOCK_CONTACT_RESPONSE = {
    "data": [
        {
            "id": "12345",
            "type": "contacts",
            "attributes": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@acme.com",
                "phone": "555-123-4567",
                "title": "Purchasing Manager",
                "custom": {
                    "assigned_isr": "Joey Smith",
                    "assigned_osr": "Sarah Johnson",
                    "status": "Active",
                    "city": "Portland",
                    "state": "OR"
                },
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2026-02-20T14:30:00Z"
            },
            "relationships": {
                "company": {"data": {"id": "999", "type": "companies"}}
            }
        }
    ],
    "meta": {
        "pagination": {
            "current_page": 1,
            "per_page": 100,
            "total_pages": 1,
            "total_entries": 1
        }
    }
}

MOCK_COMPANY_RESPONSE = {
    "data": [
        {
            "id": "999",
            "type": "companies",
            "attributes": {
                "name": "ACME Corporation",
                "website": "https://www.acme.com",
                "phone": "555-987-6543",
                "custom": {
                    "assigned_isr": "Joey Smith",
                    "status": "Active",
                    "city": "Portland",
                    "state": "OR",
                    "industry": "Manufacturing"
                },
                "created_at": "2024-06-01T08:00:00Z",
                "updated_at": "2026-02-15T11:00:00Z"
            }
        }
    ],
    "meta": {
        "pagination": {
            "current_page": 1,
            "per_page": 100,
            "total_pages": 1
        }
    }
}

MOCK_OPPORTUNITY_RESPONSE = {
    "data": [
        {
            "id": "5678",
            "type": "opportunities",
            "attributes": {
                "name": "Q1 2026 Packaging Order",
                "stage": "Negotiation",
                "value": 50000,
                "close_date": "2026-03-31",
                "custom": {
                    "owner": "Joey Smith"
                },
                "created_at": "2026-01-10T09:00:00Z",
                "updated_at": "2026-02-25T16:00:00Z"
            },
            "relationships": {
                "company": {"data": {"id": "999", "type": "companies"}},
                "contact": {"data": {"id": "12345", "type": "contacts"}}
            }
        }
    ],
    "meta": {
        "pagination": {
            "current_page": 1,
            "per_page": 100,
            "total_pages": 1
        }
    }
}


# =============================================================================
# UTILITY FUNCTION TESTS
# =============================================================================

class TestUtilityFunctions:
    """Test utility/helper functions."""
    
    def test_calculate_name_similarity_exact(self):
        """Test exact match after normalization."""
        score = calculate_name_similarity("ACME Corp", "Acme Corporation")
        # After normalization both become "ACME"
        assert score >= 0.8
    
    def test_calculate_name_similarity_fuzzy(self):
        """Test fuzzy matching."""
        score = calculate_name_similarity("Tumalo Creek Transportation", "Tumalo Creek Transport")
        assert score >= 0.8
    
    def test_calculate_name_similarity_different(self):
        """Test different names have low score."""
        score = calculate_name_similarity("ACME Corp", "XYZ Industries")
        assert score < 0.5
    
    def test_extract_email_domain(self):
        """Test email domain extraction."""
        assert extract_email_domain("john@acme.com") == "acme.com"
        assert extract_email_domain("billing@tumalo-creek.com") == "tumalo-creek.com"
        assert extract_email_domain("invalid") is None
        assert extract_email_domain("") is None
    
    def test_normalize_phone(self):
        """Test phone normalization."""
        assert normalize_phone("555-123-4567") == "5551234567"
        assert normalize_phone("(555) 123-4567") == "5551234567"
        assert normalize_phone("+1 555 123 4567") == "15551234567"


# =============================================================================
# TRANSFORM FUNCTION TESTS
# =============================================================================

class TestTransformFunctions:
    """Test data transformation functions."""
    
    def test_transform_contact(self):
        """Test contact transformation from JSON:API format."""
        raw = MOCK_CONTACT_RESPONSE["data"][0]
        contact = transform_contact(raw)
        
        assert contact["spiro_id"] == "12345"
        assert contact["first_name"] == "John"
        assert contact["last_name"] == "Doe"
        assert contact["full_name"] == "John Doe"
        assert contact["email"] == "john.doe@acme.com"
        assert contact["email_domain"] == "acme.com"
        assert contact["phone"] == "555-123-4567"
        assert contact["company_id"] == "999"
        assert contact["assigned_isr"] == "Joey Smith"
        assert contact["assigned_osr"] == "Sarah Johnson"
        assert contact["status"] == "Active"
        assert contact["city"] == "Portland"
        assert contact["state"] == "OR"
    
    def test_transform_company(self):
        """Test company transformation from JSON:API format."""
        raw = MOCK_COMPANY_RESPONSE["data"][0]
        company = transform_company(raw)
        
        assert company["spiro_id"] == "999"
        assert company["name"] == "ACME Corporation"
        assert company["name_normalized"] == "ACME CORPORATION"
        assert company["website"] == "https://www.acme.com"
        assert company["email_domain"] == "acme.com"
        assert company["assigned_isr"] == "Joey Smith"
        assert company["city"] == "Portland"
        assert company["state"] == "OR"
        assert company["industry"] == "Manufacturing"
    
    def test_transform_opportunity(self):
        """Test opportunity transformation from JSON:API format."""
        raw = MOCK_OPPORTUNITY_RESPONSE["data"][0]
        opp = transform_opportunity(raw)
        
        assert opp["spiro_id"] == "5678"
        assert opp["name"] == "Q1 2026 Packaging Order"
        assert opp["company_id"] == "999"
        assert opp["contact_id"] == "12345"
        assert opp["stage"] == "Negotiation"
        assert opp["value"] == 50000
        assert opp["close_date"] == "2026-03-31"


# =============================================================================
# SYNC SERVICE TESTS
# =============================================================================

class TestSpiroSyncService:
    """Test Spiro sync service with mocked API."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = MagicMock()
        
        # Mock collections
        db.spiro_contacts = MagicMock()
        db.spiro_contacts.update_one = AsyncMock()
        
        db.spiro_companies = MagicMock()
        db.spiro_companies.update_one = AsyncMock()
        
        db.spiro_opportunities = MagicMock()
        db.spiro_opportunities.update_one = AsyncMock()
        
        db.spiro_sync_status = MagicMock()
        db.spiro_sync_status.find_one = AsyncMock(return_value=None)
        db.spiro_sync_status.update_one = AsyncMock()
        
        return db
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock Spiro client."""
        client = MagicMock()
        client.is_configured.return_value = True
        client.list_contacts = AsyncMock(return_value=MOCK_CONTACT_RESPONSE)
        client.list_companies = AsyncMock(return_value=MOCK_COMPANY_RESPONSE)
        client.list_opportunities = AsyncMock(return_value=MOCK_OPPORTUNITY_RESPONSE)
        return client
    
    @pytest.mark.asyncio
    async def test_sync_contacts(self, mock_db, mock_client):
        """Test contact sync."""
        with patch('services.spiro.spiro_sync.is_spiro_enabled', return_value=True):
            service = SpiroSyncService(mock_db, mock_client)
            result = await service.sync_contacts()
        
        assert result["success"] is True
        assert result["records"] == 1
        assert result["entity_type"] == "contacts"
        mock_db.spiro_contacts.update_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_sync_companies(self, mock_db, mock_client):
        """Test company sync."""
        with patch('services.spiro.spiro_sync.is_spiro_enabled', return_value=True):
            service = SpiroSyncService(mock_db, mock_client)
            result = await service.sync_companies()
        
        assert result["success"] is True
        assert result["records"] == 1
        mock_db.spiro_companies.update_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_sync_disabled(self, mock_db, mock_client):
        """Test sync when Spiro is disabled."""
        with patch('services.spiro.spiro_sync.is_spiro_enabled', return_value=False):
            service = SpiroSyncService(mock_db, mock_client)
            result = await service.sync_contacts()
        
        assert result["success"] is False
        assert "disabled" in result["error"].lower()


# =============================================================================
# CONTEXT GENERATOR TESTS
# =============================================================================

class TestSpiroContextGenerator:
    """Test Spiro context generator."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database with sample data."""
        db = MagicMock()
        
        # Mock company collection
        mock_companies_cursor = MagicMock()
        mock_companies_cursor.to_list = AsyncMock(return_value=[
            {
                "spiro_id": "999",
                "name": "ACME Corporation",
                "name_normalized": "ACME CORPORATION",
                "email_domain": "acme.com",
                "phone": "5559876543",
                "city": "Portland",
                "state": "OR",
                "assigned_isr": "Joey Smith",
                "assigned_osr": "Sarah Johnson"
            },
            {
                "spiro_id": "888",
                "name": "Tumalo Creek Transportation",
                "name_normalized": "TUMALO CREEK TRANSPORTATION",
                "email_domain": "tumalo-creek.com",
                "phone": "5551234567",
                "city": "Bend",
                "state": "OR",
                "assigned_isr": "Mike Davis"
            }
        ])
        db.spiro_companies = MagicMock()
        db.spiro_companies.find = MagicMock(return_value=mock_companies_cursor)
        
        # Mock contact collection
        mock_contacts_cursor = MagicMock()
        mock_contacts_cursor.to_list = AsyncMock(return_value=[
            {
                "spiro_id": "12345",
                "full_name": "John Doe",
                "email": "john@acme.com",
                "email_domain": "acme.com",
                "company_id": "999",
                "assigned_isr": "Joey Smith"
            }
        ])
        db.spiro_contacts = MagicMock()
        db.spiro_contacts.find = MagicMock(return_value=mock_contacts_cursor)
        
        # Mock opportunity collection
        mock_opps_cursor = MagicMock()
        mock_opps_cursor.to_list = AsyncMock(return_value=[])
        db.spiro_opportunities = MagicMock()
        db.spiro_opportunities.find = MagicMock(return_value=mock_opps_cursor)
        
        return db
    
    @pytest.mark.asyncio
    async def test_generate_context_by_name(self, mock_db):
        """Test context generation with name matching."""
        with patch('services.spiro.spiro_context.is_spiro_enabled', return_value=True):
            generator = SpiroContextGenerator(mock_db)
            context = await generator.generate_context(vendor_name="ACME Corp")
        
        assert context.enabled is True
        assert len(context.matched_companies) > 0
        assert context.matched_companies[0].name == "ACME Corporation"
        assert context.confidence_signals["has_company_match"] is True
    
    @pytest.mark.asyncio
    async def test_generate_context_by_email_domain(self, mock_db):
        """Test context generation with email domain matching."""
        with patch('services.spiro.spiro_context.is_spiro_enabled', return_value=True):
            generator = SpiroContextGenerator(mock_db)
            context = await generator.generate_context(
                vendor_name="Unknown Company",
                vendor_email="billing@acme.com"
            )
        
        assert context.enabled is True
        assert context.confidence_signals["email_domain_match"] is True
    
    @pytest.mark.asyncio
    async def test_generate_context_disabled(self, mock_db):
        """Test context generation when Spiro is disabled."""
        with patch('services.spiro.spiro_context.is_spiro_enabled', return_value=False):
            generator = SpiroContextGenerator(mock_db)
            context = await generator.generate_context(vendor_name="ACME Corp")
        
        assert context.enabled is False
        assert "disabled" in context.error.lower()
    
    @pytest.mark.asyncio
    async def test_context_to_dict(self, mock_db):
        """Test SpiroContext serialization."""
        with patch('services.spiro.spiro_context.is_spiro_enabled', return_value=True):
            generator = SpiroContextGenerator(mock_db)
            context = await generator.generate_context(vendor_name="Tumalo Creek")
        
        context_dict = context.to_dict()
        
        assert "matched_companies" in context_dict
        assert "matched_contacts" in context_dict
        assert "confidence_signals" in context_dict
        assert "generated_at" in context_dict
        assert "has_matches" in context_dict


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Test error handling and graceful degradation."""
    
    @pytest.mark.asyncio
    async def test_sync_handles_api_error(self):
        """Test that sync handles API errors gracefully."""
        mock_db = MagicMock()
        mock_db.spiro_sync_status = MagicMock()
        mock_db.spiro_sync_status.find_one = AsyncMock(return_value=None)
        mock_db.spiro_sync_status.update_one = AsyncMock()
        
        mock_client = MagicMock()
        mock_client.is_configured.return_value = True
        mock_client.list_contacts = AsyncMock(return_value=None)  # Simulates API error
        
        with patch('services.spiro.spiro_sync.is_spiro_enabled', return_value=True):
            service = SpiroSyncService(mock_db, mock_client)
            result = await service.sync_contacts()
        
        # Should complete without raising exception
        assert result["records"] == 0
    
    @pytest.mark.asyncio
    async def test_context_handles_db_error(self):
        """Test that context generator handles DB errors gracefully."""
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(side_effect=Exception("DB connection error"))
        mock_db.spiro_companies = MagicMock()
        mock_db.spiro_companies.find = MagicMock(return_value=mock_cursor)
        
        with patch('services.spiro.spiro_context.is_spiro_enabled', return_value=True):
            generator = SpiroContextGenerator(mock_db)
            context = await generator.generate_context(vendor_name="Test")
        
        # Should return context with error, not raise exception
        assert context.error is not None


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
