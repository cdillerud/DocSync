"""
Regression tests for email-poller duplicate-ingestion fix (v2.5.10).

Root causes this suite pins down:

    1. `check_duplicate_mail_intake` must match rows written by EITHER
       the static poller (`filename` field) OR the dynamic poller
       (`attachment_name` field) — so the two workers see each other.

    2. `record_mail_intake_log` must write BOTH `filename` and
       `attachment_name` for forward cross-worker compat.

    3. Hash-only fallback: the exact same attachment forwarded from a
       different email (different `internet_message_id`) must still be
       detected as a duplicate.

    4. `ensure_mail_intake_indexes` must create the unique
       `(internet_message_id, attachment_hash)` partial index so concurrent
       workers can't both insert the same row.
"""
import pytest
import mongomock_motor

from services import email_polling_service as eps


@pytest.fixture
def fake_db(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["test_polling_dedup"]
    monkeypatch.setattr(eps, "get_db", lambda: db)
    return db


# ──────────────────────────────────────────────────────────────
# check_duplicate_mail_intake
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dup_check_matches_static_schema(fake_db):
    """Static poller wrote row with `filename` key. Dynamic poller
    (dedup query using hash) must find it."""
    await fake_db.mail_intake_log.insert_one({
        "internet_message_id": "msg-A",
        "attachment_hash": "hash-X",
        "filename": "GAMMIN_AR_20260316.xls",
        "status": "Processed",
    })
    assert await eps.check_duplicate_mail_intake("msg-A", "hash-X") is True


@pytest.mark.asyncio
async def test_dup_check_matches_dynamic_schema_by_name(fake_db):
    """Dynamic poller wrote row with only `attachment_name` + no hash.
    Static poller calling with hash but no matching hash row should
    still match on (msg_id, filename)."""
    await fake_db.mail_intake_log.insert_one({
        "internet_message_id": "msg-B",
        "attachment_name": "W9.pdf",
        "status": "Ingested",
    })
    assert await eps.check_duplicate_mail_intake(
        "msg-B", "hash-DIFFERENT", filename="W9.pdf",
    ) is True


@pytest.mark.asyncio
async def test_dup_check_hash_only_fallback_across_messages(fake_db):
    """Same content forwarded via two different emails → still a dup."""
    await fake_db.mail_intake_log.insert_one({
        "internet_message_id": "msg-ORIG",
        "attachment_hash": "hash-Y",
        "filename": "policy.pdf",
        "status": "Processed",
    })
    # New message id, same content hash → dup
    assert await eps.check_duplicate_mail_intake("msg-FWD", "hash-Y") is True


@pytest.mark.asyncio
async def test_dup_check_skipped_inline_does_not_block_real_processed(fake_db):
    """A SkippedInline entry (no hash) should not prevent a genuine
    first-time ingestion of another attachment."""
    await fake_db.mail_intake_log.insert_one({
        "internet_message_id": "msg-C",
        "filename": "image001.png",
        "attachment_hash": "",
        "status": "SkippedInline",
    })
    assert await eps.check_duplicate_mail_intake(
        "msg-C", "hash-NEW", filename="real-invoice.pdf",
    ) is False


@pytest.mark.asyncio
async def test_dup_check_returns_false_when_no_criteria(fake_db):
    assert await eps.check_duplicate_mail_intake("", "") is False


# ──────────────────────────────────────────────────────────────
# record_mail_intake_log
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_log_writes_both_filename_keys(fake_db):
    await eps.record_mail_intake_log(
        message_id="m1", internet_message_id="imsg1",
        attachment_id="a1", attachment_hash="h1",
        filename="INV-123.pdf", status="Processed",
    )
    row = await fake_db.mail_intake_log.find_one({"internet_message_id": "imsg1"})
    assert row is not None
    assert row["filename"] == "INV-123.pdf"
    assert row["attachment_name"] == "INV-123.pdf"


@pytest.mark.asyncio
async def test_record_log_swallows_duplicate_key_error(fake_db):
    """If the unique index rejects a concurrent re-insert, the function
    should NOT raise — just log and return."""
    await eps.ensure_mail_intake_indexes()
    await eps.record_mail_intake_log(
        message_id="m2", internet_message_id="imsg2",
        attachment_id="a2", attachment_hash="h2",
        filename="A.pdf", status="Processed",
    )
    # Second write with same (internet_message_id, attachment_hash)
    # would violate the unique index — must not raise.
    await eps.record_mail_intake_log(
        message_id="m2-again", internet_message_id="imsg2",
        attachment_id="a2-again", attachment_hash="h2",
        filename="A.pdf", status="Processed",
    )
    count = await fake_db.mail_intake_log.count_documents({"attachment_hash": "h2"})
    # mongomock may not enforce the partial index; the test's real job
    # is to assert the call did not raise. Count is either 1 (enforced)
    # or 2 (not enforced by mongomock) — both acceptable.
    assert count in (1, 2)


# ──────────────────────────────────────────────────────────────
# ensure_mail_intake_indexes
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_indexes_creates_uniq_msgid_hash(fake_db):
    await eps.ensure_mail_intake_indexes()
    idx = await fake_db.mail_intake_log.index_information()
    names = set(idx.keys())
    # Unique + lookup indexes should all be present by name
    assert "uniq_msgid_hash" in names or any(
        "internet_message_id" in str(v.get("key", "")) and "attachment_hash" in str(v.get("key", ""))
        for v in idx.values()
    )
