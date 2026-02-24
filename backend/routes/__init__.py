"""
GPI Document Hub - Routes Package

Modular API routers for the Document Hub.
"""

from .auth import router as auth_router
from .documents import router as documents_router, set_db as set_documents_db
from .workflows import router as workflows_router, set_dependencies as set_workflows_deps
from .config import router as config_router, set_db as set_config_db
from .dashboard import router as dashboard_router, set_db as set_dashboard_db

__all__ = [
    'auth_router',
    'documents_router', 'set_documents_db',
    'workflows_router', 'set_workflows_deps',
    'config_router', 'set_config_db',
    'dashboard_router', 'set_dashboard_db',
]
