"""
Where a document's file bytes live, and the one way to read them.

2026-11-01: hub_documents carried every file as base64 in
``file_content_b64`` -- about 90% of the collection's 13.5 GB -- so every
unindexed query and every cache eviction paid for bytes almost nothing
needed. Measured the same day: all 27,103 records with the field also had
the file on the uploads volume. The volume is the primary copy; the
MongoDB backup moves to its own collection, ``document_files``
({"id", "file_content_b64", "file_name", "file_size", "stored_at"}), where
only a disk miss ever reads it.

Read order in load_bytes: uploads volume -> document_files -> the legacy
hub_documents.file_content_b64 (until a backfill copies it across and
unsets it). Nothing outside this module should touch file_content_b64.
"""

import asyncio
import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

# paths imports only pathlib, so this cannot cycle back into routers/services.
from paths import UPLOAD_DIR

logger = logging.getLogger(__name__)

# Largest base64 backup kept in MongoDB. Base64 adds a third, and a file over
# ~12 MB would push the record past the 16 MB MongoDB document limit; such
# files live on the uploads volume only. (Moved here from
# document_bytes_intake_service, which re-exports it.)
MAX_INLINE_B64_BYTES = 12 * 1024 * 1024

# Reads above this go to a worker thread so a big PDF does not stall the loop.
_THREAD_READ_BYTES = 1024 * 1024

DocOrId = Union[str, Dict[str, Any]]


def upload_path(doc_id: str, file_name: str = "") -> Optional[Path]:
    """The document's file on the uploads volume: ``UPLOAD_DIR/doc_id``, else
    ``UPLOAD_DIR/{doc_id}{ext}`` with ext from file_name (same resolution as
    routers.documents._resolve_file_path). None when neither exists."""
    if not doc_id:
        return None
    path = UPLOAD_DIR / doc_id
    if path.exists():
        return path
    ext = Path(file_name or "").suffix
    if ext:
        path_with_ext = UPLOAD_DIR / f"{doc_id}{ext}"
        if path_with_ext.exists():
            return path_with_ext
    return None


def read_upload(doc_id: str, file_name: str = "", max_bytes: Optional[int] = None) -> Optional[bytes]:
    """Synchronous disk-only read, for sync callers (folder routing's PDF
    text). None when the file is missing, unreadable or over max_bytes."""
    path = upload_path(doc_id, file_name)
    if not path:
        return None
    try:
        if max_bytes is not None and path.stat().st_size > max_bytes:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _split(doc_or_id: DocOrId, file_name: str = ""):
    if isinstance(doc_or_id, dict):
        return str(doc_or_id.get("id") or ""), file_name or str(doc_or_id.get("file_name") or ""), doc_or_id
    return str(doc_or_id or ""), file_name, None


def _decode(b64: Any) -> Optional[bytes]:
    if not isinstance(b64, str) or not b64:
        return None
    try:
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return None


async def load_backup(db, doc_or_id: DocOrId) -> Optional[bytes]:
    """The MongoDB copy only: document_files, then the legacy
    hub_documents.file_content_b64. For flows that restore a missing file to
    disk; everything else wants load_bytes."""
    doc_id, _, doc = _split(doc_or_id)
    if not doc_id:
        return None
    rec = await db.document_files.find_one({"id": doc_id}, {"_id": 0, "file_content_b64": 1})
    data = _decode((rec or {}).get("file_content_b64"))
    if data is not None:
        return data
    # Legacy field: use the caller's copy when it already fetched it (a None
    # there means the record has none), otherwise fetch that one field only.
    if doc is not None and "file_content_b64" in doc:
        return _decode(doc.get("file_content_b64"))
    legacy = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_content_b64": 1})
    return _decode((legacy or {}).get("file_content_b64"))


async def load_bytes(db, doc_or_id: DocOrId, file_name: str = "") -> Optional[bytes]:
    """A document's file bytes: uploads volume, then the MongoDB backup.
    ``doc_or_id`` is the id or a hub_documents dict carrying ``id`` (and
    ideally ``file_name``, for the ``{id}{ext}`` disk name). None when no copy
    exists."""
    doc_id, name, _ = _split(doc_or_id, file_name)
    if not doc_id:
        return None
    path = upload_path(doc_id, name)
    if path:
        try:
            if path.stat().st_size > _THREAD_READ_BYTES:
                return await asyncio.to_thread(path.read_bytes)
            return path.read_bytes()
        except OSError as exc:
            logger.warning("[FileBytes] %s on disk but unreadable: %s", doc_id[:8], exc)
    return await load_backup(db, doc_or_id)


async def save_backup(db, doc_id: str, file_name: str, data: bytes) -> bool:
    """Store the MongoDB backup copy of a document's file in document_files
    (upsert). Skipped, returning False, for files whose base64 would exceed
    MAX_INLINE_B64_BYTES -- those live on the uploads volume only."""
    if not doc_id or not data:
        return False
    if (len(data) + 2) // 3 * 4 > MAX_INLINE_B64_BYTES:
        logger.info("[FileBytes] %s is %d bytes; not storing the base64 backup in MongoDB",
                    file_name, len(data))
        return False
    await db.document_files.update_one(
        {"id": doc_id},
        {"$set": {
            "id": doc_id,
            "file_content_b64": base64.b64encode(data).decode("ascii"),
            "file_name": file_name,
            "file_size": len(data),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return True


async def delete_backup(db, doc_ids) -> None:
    """Drop the backups of deleted documents (an id or a list of ids)."""
    ids = [doc_ids] if isinstance(doc_ids, str) else [i for i in (doc_ids or []) if i]
    if ids:
        await db.document_files.delete_many({"id": {"$in": ids}})


def has_bytes_filter() -> Dict[str, Any]:
    """Mongo filter for "this document has a file", replacing
    ``{"file_content_b64": {"$exists": True, "$ne": None}}``.

    file_size is set by every intake path and survives the backup's move out
    of hub_documents. Probe 2026-11-01 (29,448 records): file_size > 0 on
    29,439, including all 27,103 that had the base64 field and 2,224 whose
    file is on disk only; 112 have a size but no copy anywhere (load_bytes
    returns None for those, which every caller already handles)."""
    return {"file_size": {"$gt": 0}}


async def ensure_document_files_index(db) -> None:
    """Unique index on document_files.id: load_backup looks up by id, and the
    upsert in save_backup must never create two copies. Safe to repeat."""
    await db.document_files.create_index("id", unique=True, name="uniq_document_files_id")
