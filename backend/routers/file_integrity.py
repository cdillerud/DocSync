"""
File Integrity Check — Find and flag documents with missing/broken file references.

Documents without accessible files can't be processed, previewed, or extracted from.
Instead of sitting silently in the queue, they get flagged as "file_missing" so users
can re-upload or dismiss them.

Endpoints:
  POST /api/file-integrity/scan       — Scan and flag docs with missing files
  POST /api/file-integrity/dry-run    — Preview what would be flagged
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from deps import get_db

logger = logging.getLogger("file_integrity")
router = APIRouter(prefix="/file-integrity", tags=["File Integrity"])

ROOT_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT_DIR / "uploads"


@router.post("/dry-run")
async def dry_run():
    """Preview which docs have missing files."""
    db = get_db()

    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate"]
    docs = await db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "auto_cleared": {"$ne": True},
            "file_missing": {"$ne": True},
            "status": {"$nin": TERMINAL},
        },
        {"_id": 0, "id": 1, "file_name": 1, "source": 1, "doc_type": 1,
         "document_type": 1, "status": 1, "created_utc": 1},
    ).to_list(5000)

    missing = []
    found = 0

    for doc in docs:
        file_path = UPLOAD_DIR / doc["id"]
        if not file_path.exists():
            missing.append({
                "id": doc["id"],
                "file_name": doc.get("file_name", "?"),
                "source": doc.get("source", "?"),
                "type": doc.get("doc_type") or doc.get("document_type") or "unknown",
            })
        else:
            found += 1

    by_source = {}
    for m in missing:
        by_source.setdefault(m["source"], 0)
        by_source[m["source"]] += 1

    return {
        "total_scanned": len(docs),
        "files_found": found,
        "files_missing": len(missing),
        "by_source": by_source,
        "sample_missing": missing[:20],
    }


@router.post("/scan")
async def scan_and_flag():
    """Scan pending docs and flag those with missing files."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate"]
    docs = await db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "file_missing": {"$ne": True},
            "status": {"$nin": TERMINAL},
        },
        {"_id": 0, "id": 1, "file_name": 1, "source": 1},
    ).to_list(5000)

    flagged = 0
    for doc in docs:
        file_path = UPLOAD_DIR / doc["id"]
        if not file_path.exists():
            await db.hub_documents.update_one(
                {"id": doc["id"]},
                {"$set": {
                    "file_missing": True,
                    "file_missing_flagged_utc": now,
                    "workflow_status": "file_missing",
                    "status": "FileMissing",
                }},
            )
            flagged += 1

    return {
        "total_scanned": len(docs),
        "flagged_missing": flagged,
        "timestamp": now,
    }
