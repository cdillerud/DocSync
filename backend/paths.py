"""
Filesystem paths shared across the backend.

Authoritative home for Path constants previously declared in server.py.
Landed in Phase 3 Step 4d.2a (2026-04-23).
"""
from pathlib import Path

ROOT_DIR = Path(__file__).parent
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
