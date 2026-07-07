"""
Shared upload storage path.

Extracted verbatim from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md). Used by routes/documents.py and several groups still
in server.py (ingestion/reprocess flows) that store the original uploaded
file on disk for retry/resubmit.
"""
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
