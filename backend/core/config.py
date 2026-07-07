"""
Shared config/env constants.

Extracted verbatim from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md). No behavior change: identical env var names and
defaults. server.py and routes/*.py import from here instead of redefining.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
JWT_SECRET = os.environ.get('JWT_SECRET', 'gpi-hub-secret-key')
# Feature flag for Phase 4: CREATE_DRAFT_HEADER (Sandbox only)
ENABLE_CREATE_DRAFT_HEADER = os.environ.get('ENABLE_CREATE_DRAFT_HEADER', 'false').lower() == 'true'
# AI Classification Config
AI_CLASSIFICATION_ENABLED = os.environ.get('AI_CLASSIFICATION_ENABLED', 'true').lower() == 'true'
AI_CLASSIFICATION_THRESHOLD = float(os.environ.get('AI_CLASSIFICATION_THRESHOLD', '0.8'))
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
# Phase 7 C1: Email Polling Config (Observation Infrastructure)
EMAIL_POLLING_ENABLED = os.environ.get('EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('EMAIL_POLLING_INTERVAL_MINUTES', '5'))
EMAIL_POLLING_USER = os.environ.get('EMAIL_POLLING_USER', '')  # ap@gamerpackaging.com
EMAIL_POLLING_LOOKBACK_MINUTES = int(os.environ.get('EMAIL_POLLING_LOOKBACK_MINUTES', '60'))
EMAIL_POLLING_MAX_MESSAGES = int(os.environ.get('EMAIL_POLLING_MAX_MESSAGES', '25'))
EMAIL_POLLING_MAX_ATTACHMENT_MB = int(os.environ.get('EMAIL_POLLING_MAX_ATTACHMENT_MB', '25'))
# Sales Email Polling Config (Shadow Mode)
SALES_EMAIL_POLLING_ENABLED = os.environ.get('SALES_EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
SALES_EMAIL_POLLING_USER = os.environ.get('SALES_EMAIL_POLLING_USER', '')  # hub-sales-intake@gamerpackaging.com
SALES_EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('SALES_EMAIL_POLLING_INTERVAL_MINUTES', '5'))
# Separate email app credentials (for Mail.Read access)
EMAIL_CLIENT_ID = os.environ.get('EMAIL_CLIENT_ID', '')
EMAIL_CLIENT_SECRET = os.environ.get('EMAIL_CLIENT_SECRET', '')
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET', '')
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME', 'gamerpackaging.sharepoint.com')
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH', '/sites/GPI-DocumentHub-Test')
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Documents')
