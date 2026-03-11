"""
GPI Document Hub - Centralized Dependencies

Provides shared access to database, services, and configuration
for all router modules. Avoids circular imports by using lazy getters.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DATABASE (set once at startup from server.py)
# ---------------------------------------------------------------------------
_db: AsyncIOMotorDatabase = None


def set_db(database: AsyncIOMotorDatabase):
    global _db
    _db = database


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized. Call set_db() first.")
    return _db


# ---------------------------------------------------------------------------
# CONFIG — read from environment (set once at import time)
# ---------------------------------------------------------------------------
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
JWT_SECRET = os.environ.get('JWT_SECRET', 'gpi-hub-secret-key')
ENABLE_CREATE_DRAFT_HEADER = os.environ.get('ENABLE_CREATE_DRAFT_HEADER', 'false').lower() == 'true'
AI_CLASSIFICATION_ENABLED = os.environ.get('AI_CLASSIFICATION_ENABLED', 'true').lower() == 'true'
AI_CLASSIFICATION_THRESHOLD = float(os.environ.get('AI_CLASSIFICATION_THRESHOLD', '0.8'))

# Email polling
EMAIL_POLLING_ENABLED = os.environ.get('EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('EMAIL_POLLING_INTERVAL_MINUTES', '5'))
EMAIL_POLLING_USER = os.environ.get('EMAIL_POLLING_USER', '')
EMAIL_POLLING_LOOKBACK_MINUTES = int(os.environ.get('EMAIL_POLLING_LOOKBACK_MINUTES', '60'))
EMAIL_POLLING_MAX_MESSAGES = int(os.environ.get('EMAIL_POLLING_MAX_MESSAGES', '25'))
EMAIL_POLLING_MAX_ATTACHMENT_MB = int(os.environ.get('EMAIL_POLLING_MAX_ATTACHMENT_MB', '25'))
SALES_EMAIL_POLLING_ENABLED = os.environ.get('SALES_EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
SALES_EMAIL_POLLING_USER = os.environ.get('SALES_EMAIL_POLLING_USER', '')
SALES_EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('SALES_EMAIL_POLLING_INTERVAL_MINUTES', '5'))

# MS Identity / BC / Graph
EMAIL_CLIENT_ID = os.environ.get('EMAIL_CLIENT_ID', '')
EMAIL_CLIENT_SECRET = os.environ.get('EMAIL_CLIENT_SECRET', '')
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')
BC_READ_ENVIRONMENT = os.environ.get('BC_PROD_ENVIRONMENT', os.environ.get('BC_ENVIRONMENT', ''))
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET', '')
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME', 'gamerpackaging.sharepoint.com')
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH', '/sites/GPI-DocumentHub-Test')
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Documents')
