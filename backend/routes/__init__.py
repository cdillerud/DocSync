"""
GPI Document Hub - Routes Package

Modular API routers for the Document Hub.
"""

from .auth import router as auth_router
from .documents import router as documents_router
from .workflows import router as workflows_router, set_dependencies as set_workflows_deps
from .config import router as config_router
from .dashboard import router as dashboard_router

__all__ = [
    'auth_router',
    'documents_router',
    'workflows_router', 'set_workflows_deps',
    'config_router',
    'dashboard_router',
]
