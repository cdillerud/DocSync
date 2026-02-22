"""
GPI Document Hub - Legacy Migration Module

This module provides tools for migrating documents from legacy systems
(Square9, Zetadocs) into the GPI Document Hub.

Components:
- LegacyDocumentSource: Abstract interface for legacy data sources
- JsonFileSource: JSON file-based implementation for testing
- MigrationJob: Core migration logic with dry run support
- WorkflowInitializer: Determines initial workflow states for migrated docs
"""

from .sources import LegacyDocumentSource, JsonFileSource, InMemorySource
from .job import MigrationJob, MigrationResult
from .workflow_initializer import WorkflowInitializer

__all__ = [
    'LegacyDocumentSource',
    'JsonFileSource',
    'InMemorySource',
    'MigrationJob',
    'MigrationResult',
    'WorkflowInitializer',
]
