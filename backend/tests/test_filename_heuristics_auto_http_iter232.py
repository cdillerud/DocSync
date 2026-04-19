"""HTTP-level regression for v2.5.10 auto-proposed filename-heuristic rules.

Covers (against REACT_APP_BACKEND_URL):
  * 5 new admin endpoints: auto-propose, auto-apply (dry + execute),
    custom-rules listing, toggle.
  * Full round-trip: seed classified + unmatched docs → execute → verify
    row lands in filename_heuristic_custom_rules → list → toggle.
  * Regression: pre-existing /filename-heuristics/* endpoints + triage
    duplicate-docs/scan + email-polling/status + documents.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = f"{BASE_URL}/api/admin"
TIMEOUT = 60


# ---------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def db():
    """Direct Mongo handle for seeding + verification."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


@pytest.fixture(scope="module")
def seed_tag():
    return f"TEST_iter232_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def seed_data(db, seed_tag):
    """Seed 6 classified docs (PurchaseOrder majority) + 4 unmatched
    docs with the same vendor + shape so auto-propose emits >=1 rule."""
    async def _seed():
        vendor_canonical = f"{seed_tag}_VENDOR"
        now = datetime.now(timezone.utc).isoformat()
        docs = []
        # 6 classified PurchaseOrder docs (majority) — excluded from
        # unmatched filter because doc_type is set & not unknown
        for i in range(6):
            docs.append({
                "id": f"{seed_tag}_clf_{i}",
                "file_name": f"PO{1000+i}.pdf",
                "vendor_canonical": vendor_canonical,
                "vendor_name": vendor_canonical,
                "doc_type": "PurchaseOrder",
                "document_type": "PurchaseOrder",
                "suggested_job_type": "PurchaseOrder",
                "filename_heuristic_applied_at": None,
                "created_at": now,
                "seed_tag": seed_tag,
            })
        # 4 unmatched docs sharing shape A+#+.A+ (letters+digits.letters)
        for i in range(4):
            docs.append({
                "id": f"{seed_tag}_unm_{i}",
                "file_name": f"INV{2000+i}.pdf",
                "vendor_canonical": vendor_canonical,
                "vendor_name": vendor_canonical,
                "doc_type": "Unknown",
                "document_type": "Unknown",
                "suggested_job_type": "Unknown",
                "filename_heuristic_applied_at": None,
                # BC evidence empty
                "bc_purchase_invoice_no": "",
                "bc_record_no": "",
                "bc_document_no": "",
                "bc_record_id": "",
                "created_at": now,
                "seed_tag": seed_tag,
            })
        await db.hub_documents.insert_many(docs)
        return vendor_canonical

    vendor = asyncio.get_event_loop().run_until_complete(_seed())
    yield {"vendor_canonical": vendor, "seed_tag": seed_tag}

    async def _cleanup():
        await db.hub_documents.delete_many({"seed_tag": seed_tag})
        await db.filename_heuristic_custom_rules.delete_many(
            {"vendor_canonical": vendor}
        )
    asyncio.get_event_loop().run_until_complete(_cleanup())


# ---------------------------------------------------------- new endpoints
class TestAutoProposeEndpoint:
    def test_auto_propose_returns_200_and_shape(self, client):
        r = client.get(f"{ADMIN}/filename-heuristics/auto-propose",
                       timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        required = {
            "proposals", "deferred", "proposals_count", "deferred_count",
            "groups_total", "projected_coverage",
            "min_group_size", "min_vendor_samples", "min_majority_pct",
        }
        missing = required - set(data.keys())
        assert not missing, f"missing keys: {missing}"
        assert isinstance(data["proposals"], list)
        assert isinstance(data["deferred"], list)
        assert isinstance(data["proposals_count"], int)

    def test_auto_propose_param_validation(self, client):
        r = client.get(
            f"{ADMIN}/filename-heuristics/auto-propose",
            params={"min_group_size": 2, "min_vendor_samples": 3,
                    "min_majority_pct": 60.0, "limit": 500},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["min_group_size"] == 2
        assert d["min_vendor_samples"] == 3
        assert d["min_majority_pct"] == 60.0


class TestAutoApplyDryRun:
    def test_dry_run_response_shape(self, client):
        r = client.post(f"{ADMIN}/filename-heuristics/auto-apply",
                        params={"execute": False}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("eligible_count", "projected_coverage",
                  "eligible_sample", "execute"):
            assert k in d, f"{k} missing"
        assert d["execute"] is False


class TestCustomRulesListing:
    def test_list_custom_rules_returns_total_and_rules(self, client):
        r = client.get(f"{ADMIN}/filename-heuristics/custom-rules",
                       timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "total" in d and "rules" in d
        assert isinstance(d["rules"], list)
        assert d["total"] == len(d["rules"])


# ---------------------------------------------------------- full round-trip
class TestAutoApplyRoundTrip:
    """Seed → propose → dry-run → execute=true → list → toggle."""

    def test_round_trip_persist_and_toggle(self, client, db, seed_data):
        vendor = seed_data["vendor_canonical"]
        tag = seed_data["seed_tag"]

        # 1. propose with relaxed thresholds so small seed matches.
        propose = client.get(
            f"{ADMIN}/filename-heuristics/auto-propose",
            params={"min_group_size": 2, "min_vendor_samples": 3,
                    "min_majority_pct": 60.0},
            timeout=TIMEOUT,
        ).json()
        # find our vendor proposal
        ours = [p for p in propose["proposals"]
                if p.get("vendor_canonical") == vendor]
        assert ours, (
            f"seed vendor not found in proposals. "
            f"proposals_count={propose['proposals_count']}, "
            f"deferred_count={propose['deferred_count']}"
        )
        prop = ours[0]
        assert prop["doc_type"] == "PurchaseOrder"
        assert prop["confidence"] >= 0.6

        # 2. dry-run
        dry = client.post(
            f"{ADMIN}/filename-heuristics/auto-apply",
            params={"execute": False, "min_unmatched_count": 2,
                    "min_confidence": 0.6},
            timeout=TIMEOUT,
        ).json()
        assert dry["execute"] is False
        assert dry["eligible_count"] >= 1

        # 3. execute=true — persist
        ex = client.post(
            f"{ADMIN}/filename-heuristics/auto-apply",
            params={"execute": True, "min_unmatched_count": 2,
                    "min_confidence": 0.6, "actor": f"test_{tag}"},
            timeout=TIMEOUT,
        ).json()
        assert ex["execute"] is True
        assert ex["inserted_or_updated_count"] >= 1

        # 4. mongo row exists
        async def _check():
            return await db.filename_heuristic_custom_rules.find_one(
                {"vendor_canonical": vendor}
            )
        row = asyncio.get_event_loop().run_until_complete(_check())
        assert row is not None, "rule not persisted"
        assert row["doc_type"] == "PurchaseOrder"
        assert row["enabled"] is True
        assert row["origin"] == "auto_proposed"
        rule_id = row["rule_id"]

        # 5. GET /custom-rules returns it
        listed = client.get(
            f"{ADMIN}/filename-heuristics/custom-rules",
            timeout=TIMEOUT,
        ).json()
        found = [r for r in listed["rules"] if r["rule_id"] == rule_id]
        assert found, "persisted rule not in listing"

        # 6. toggle off
        t_off = client.post(
            f"{ADMIN}/filename-heuristics/custom-rules/{rule_id}/toggle",
            params={"enabled": False},
            timeout=TIMEOUT,
        )
        assert t_off.status_code == 200, t_off.text
        assert t_off.json()["enabled"] is False

        # verify in Mongo
        async def _check_off():
            return await db.filename_heuristic_custom_rules.find_one(
                {"rule_id": rule_id}
            )
        row2 = asyncio.get_event_loop().run_until_complete(_check_off())
        assert row2["enabled"] is False

        # 7. only_enabled filter excludes it
        listed_enabled = client.get(
            f"{ADMIN}/filename-heuristics/custom-rules",
            params={"only_enabled": True}, timeout=TIMEOUT,
        ).json()
        ids = [r["rule_id"] for r in listed_enabled["rules"]]
        assert rule_id not in ids

        # 8. toggle back on
        t_on = client.post(
            f"{ADMIN}/filename-heuristics/custom-rules/{rule_id}/toggle",
            params={"enabled": True}, timeout=TIMEOUT,
        )
        assert t_on.status_code == 200
        assert t_on.json()["enabled"] is True


# ---------------------------------------------------------- regression
class TestRegression:
    def test_existing_rules_endpoint(self, client):
        r = client.get(f"{ADMIN}/filename-heuristics/rules", timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_existing_preview(self, client):
        r = client.get(f"{ADMIN}/filename-heuristics/preview",
                       timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_existing_apply_dry_run(self, client):
        r = client.post(f"{ADMIN}/filename-heuristics/apply",
                        params={"execute": False}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_existing_unmatched_sample(self, client):
        r = client.get(f"{ADMIN}/filename-heuristics/unmatched-sample",
                       timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_duplicate_docs_scan(self, client):
        r = client.get(f"{ADMIN}/duplicate-docs/scan", timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_email_polling_status(self, client):
        r = client.get(f"{BASE_URL}/api/email-polling/status",
                       timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_documents_list(self, client):
        r = client.get(f"{BASE_URL}/api/documents",
                       params={"limit": 5}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
