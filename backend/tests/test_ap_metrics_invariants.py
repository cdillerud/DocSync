"""Invariants for the /api/dashboard/ap-metrics endpoint.

Guards against the 0.5% / 17 / 1 KPI bug class observed on the
Insights page on 2026-05-13:

- AP docs must be identified by `doc_type`, not `document_type`.
- Posted count must use the canonical BC posting signals
  (bc_purchase_invoice_no / bc_record_no / bc_document_no /
  bc_record_id / status=='Posted'), NOT bc_posting_status.
- Failed count must recognize bc_posting_status='failed' OR
  non-empty bc_posting_error OR final_state='auto_post_failed',
  but must NOT double-count docs that later succeeded.
- success_rate must be posted/(posted+failed), never
  posted/total_ap.
- Empty attempts denominator must yield 0, not divide-by-zero.

Pure unit tests -- no live Mongo, no HTTP, no fixtures on disk.
The dashboard router's `get_db()` is patched to return a tiny fake
that answers the queries `get_ap_metrics` makes.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

import pytest


def _matches(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    """Minimal Mongo-query matcher covering the operators used by
    `get_ap_metrics`. Intentionally small so the tests stay readable
    without pulling mongomock in just for this."""
    if not q:
        return True
    for key, cond in q.items():
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
            continue
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        if key == "$nor":
            if any(_matches(doc, sub) for sub in cond):
                return False
            continue
        # Dotted-path lookup (e.g. "validation_results.all_passed")
        if "." in key:
            parts = key.split(".")
            cur: Any = doc
            for p in parts:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    cur = None
                    break
            val = cur
        else:
            val = doc.get(key)
        if isinstance(cond, dict):
            for op, expected in cond.items():
                if op == "$ne":
                    if val == expected:
                        return False
                elif op == "$nin":
                    if val in expected:
                        return False
                elif op == "$in":
                    if val not in expected:
                        return False
                elif op == "$gte":
                    if val is None or val < expected:
                        return False
                elif op == "$exists":
                    has_key = (key in doc) if "." not in key else (val is not None)
                    if expected and not has_key:
                        return False
                    if not expected and has_key:
                        return False
                elif op == "$regex":
                    if not isinstance(val, str):
                        return False
                    flags = re.IGNORECASE if "i" in cond.get("$options", "") else 0
                    if not re.search(expected, val, flags):
                        return False
                elif op == "$options":
                    continue  # handled alongside $regex
                else:
                    raise NotImplementedError(
                        f"fake mongo: op {op!r} not supported in tests")
        else:
            if val != cond:
                return False
    return True


class _FakeCollection:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for d in self._docs if _matches(d, query))

    def find(self, query, projection=None):
        return _FakeCursor([d for d in self._docs if _matches(d, query)])

    def aggregate(self, pipeline):
        # error_breakdown is not under invariant test here; return empty
        # cursor and let the route handle it gracefully.
        return _FakeCursor([])


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_, **__):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, _length):
        return self._docs


class _FakeDB:
    def __init__(self, docs: List[Dict[str, Any]]):
        self.hub_documents = _FakeCollection(docs)


def _run(monkeypatch, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from routers import dashboard as mod
    monkeypatch.setattr(mod, "get_db", lambda: _FakeDB(docs))
    return asyncio.get_event_loop().run_until_complete(mod.get_ap_metrics())


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_docs_counted_by_doc_type_not_document_type(monkeypatch):
    """An AP doc tagged via legacy `document_type` only must NOT count.
    This is the 52x undercount bug we observed in production."""
    docs = [
        {"id": "x1", "document_type": "AP_INVOICE"},  # legacy-only
        {"id": "x2", "doc_type": "AP_INVOICE"},        # canonical
    ]
    out = _run(monkeypatch, docs)
    assert out["total_ap"] == 1, out


def test_posted_uses_canonical_signals_not_bc_posting_status(monkeypatch):
    """Posted count must include docs that carry a BC record signal
    even without `bc_posting_status`. Confirms the right field is used."""
    docs = [
        {"id": "p1", "doc_type": "AP_INVOICE",
         "bc_purchase_invoice_no": "PI-001"},
        {"id": "p2", "doc_type": "AP_INVOICE",
         "bc_record_no": "BC-002"},
        {"id": "p3", "doc_type": "AP_INVOICE",
         "bc_document_no": "DOC-003"},
        {"id": "p4", "doc_type": "AP_INVOICE",
         "bc_record_id": "id-004"},
        {"id": "p5", "doc_type": "AP_INVOICE", "status": "Posted"},
        {"id": "n1", "doc_type": "AP_INVOICE"},  # not posted
    ]
    out = _run(monkeypatch, docs)
    assert out["posted_to_bc"] == 5, out
    assert out["total_ap"] == 6


def test_failed_signal_recognized(monkeypatch):
    """All three failure indicators must register as failed."""
    docs = [
        {"id": "f1", "doc_type": "AP_INVOICE",
         "bc_posting_status": "failed"},
        {"id": "f2", "doc_type": "AP_INVOICE",
         "bc_posting_error": "Vendor not found"},
        {"id": "f3", "doc_type": "AP_INVOICE",
         "final_state": "auto_post_failed"},
        {"id": "ok", "doc_type": "AP_INVOICE"},  # clean
    ]
    out = _run(monkeypatch, docs)
    assert out["failed"] == 3, out


def test_failed_excludes_recovered_docs(monkeypatch):
    """A doc that failed once and then succeeded must count as POSTED
    only -- never as both posted AND failed."""
    docs = [
        {"id": "r1", "doc_type": "AP_INVOICE",
         "bc_posting_error": "first attempt failed",
         "bc_purchase_invoice_no": "PI-RECOVERED"},
    ]
    out = _run(monkeypatch, docs)
    assert out["posted_to_bc"] == 1
    assert out["failed"] == 0, out


def test_success_rate_is_posted_over_attempts_not_total(monkeypatch):
    """The original bug: success_rate = posted/total_ap produced 0.5%
    on a healthy system. Must be posted/(posted+failed)."""
    docs = [
        # 9 posted
        *[{"id": f"p{i}", "doc_type": "AP_INVOICE",
           "bc_purchase_invoice_no": f"PI-{i}"} for i in range(9)],
        # 1 failed
        {"id": "f1", "doc_type": "AP_INVOICE",
         "bc_posting_status": "failed"},
        # 90 still-pending
        *[{"id": f"q{i}", "doc_type": "AP_INVOICE"} for i in range(90)],
    ]
    out = _run(monkeypatch, docs)
    assert out["total_ap"] == 100
    assert out["posted_to_bc"] == 9
    assert out["failed"] == 1
    # Buggy formula would give 9/100 = 9.0. Correct = 9/10 = 90.0.
    assert out["success_rate"] == 90.0, (
        f"success_rate must be posted/(posted+failed)=90.0; "
        f"got {out['success_rate']}")


def test_success_rate_never_uses_total_ap_as_denominator(monkeypatch):
    """Regression: with many unposted docs and 100% success on
    attempts, success_rate must be 100, not a coverage ratio."""
    docs = [
        # 2 posted, 0 failed, 998 still-pending
        {"id": "p1", "doc_type": "AP_INVOICE",
         "bc_purchase_invoice_no": "PI-1"},
        {"id": "p2", "doc_type": "AP_INVOICE",
         "bc_record_no": "BC-2"},
        *[{"id": f"q{i}", "doc_type": "AP_INVOICE"} for i in range(998)],
    ]
    out = _run(monkeypatch, docs)
    assert out["posted_to_bc"] == 2
    assert out["failed"] == 0
    assert out["success_rate"] == 100.0, (
        f"100% of attempts succeeded; success_rate must be 100.0, "
        f"got {out['success_rate']} (would be 0.2 under the bug)")


def test_success_rate_zero_attempts_is_safe(monkeypatch):
    """No posted, no failed -> success_rate must be 0, never NaN/Inf
    or divide-by-zero."""
    docs = [
        {"id": "q1", "doc_type": "AP_INVOICE"},
        {"id": "q2", "doc_type": "AP_INVOICE"},
    ]
    out = _run(monkeypatch, docs)
    assert out["posted_to_bc"] == 0
    assert out["failed"] == 0
    assert out["success_rate"] == 0
    val = out["success_rate"]
    assert val == val  # NaN check
    assert val not in (float("inf"), float("-inf"))


def test_case_insensitive_ap_type_match(monkeypatch):
    """Both AP_INVOICE and AP_Invoice (+ Purchase_Invoice variants)
    must be counted -- the live corpus has both casings."""
    docs = [
        {"id": "u1", "doc_type": "AP_INVOICE"},
        {"id": "u2", "doc_type": "AP_Invoice"},
        {"id": "u3", "doc_type": "ap_invoice"},
        {"id": "u4", "doc_type": "Purchase_Invoice"},
        {"id": "u5", "doc_type": "PurchaseInvoice"},
        {"id": "x",  "doc_type": "SALES_INVOICE"},  # not AP
    ]
    out = _run(monkeypatch, docs)
    assert out["total_ap"] == 5, out


def test_response_structure_unchanged(monkeypatch):
    """Smoke: every field the frontend reads must still be present
    and non-None."""
    docs = [
        {"id": "p1", "doc_type": "AP_INVOICE",
         "bc_purchase_invoice_no": "PI-1",
         "validation_results": {"all_passed": True}},
        {"id": "f1", "doc_type": "AP_INVOICE",
         "bc_posting_status": "failed"},
    ]
    out = _run(monkeypatch, docs)
    for key in ("total_ap", "posted_to_bc", "failed", "pending_review",
                "validation_rate", "avg_time_to_post_hours",
                "success_rate", "error_breakdown"):
        assert key in out, f"missing field {key}"
        assert out[key] is not None, f"field {key} is None"
