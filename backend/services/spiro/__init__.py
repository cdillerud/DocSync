"""
GPI Document Hub - Spiro CRM Integration

This module provides integration with Spiro (Anti-CRM) to enrich document
validation with customer, vendor, and manufacturer context.

Components:
- spiro_client.py: OAuth handling and API client
- spiro_sync.py: Data synchronization service
- spiro_context.py: SpiroContext generator for document validation
- spiro_models.py: Data models and MongoDB schemas

Usage:
    from services.spiro import get_spiro_context_for_document, sync_all_spiro_data
    
    # Get Spiro context for a document
    context = await get_spiro_context_for_document(doc_metadata)
    
    # Sync all Spiro data
    result = await sync_all_spiro_data()
"""

from .spiro_client import SpiroClient, get_spiro_client
from .spiro_sync import SpiroSyncService, sync_all_spiro_data, sync_spiro_contacts
from .spiro_context import SpiroContextGenerator, get_spiro_context_for_document

__all__ = [
    'SpiroClient',
    'get_spiro_client',
    'SpiroSyncService', 
    'sync_all_spiro_data',
    'sync_spiro_contacts',
    'SpiroContextGenerator',
    'get_spiro_context_for_document'
]
