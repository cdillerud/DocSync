"""Motor Database objects raise on bool(); stable-vendor code must compare to None.

Before 2026-09-24, `if vendor_no and self.db:` raised for every vendor with a
vendor_no, so stable-vendor evaluation never completed for real documents.
"""

import pytest

from services.stable_vendor_service import StableVendorService


class _Coll:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, *args, **kwargs):
        return self.doc


class MotorLikeDB:
    def __init__(self):
        self.stable_vendor_config = _Coll()
        self.posting_pattern_analysis = _Coll()

    def __bool__(self):
        raise NotImplementedError(
            "Database objects do not implement truth value testing or bool()"
        )


class _VendorIntel:
    async def get_profile(self, vendor_id):
        return {"vendor_no": vendor_id}


@pytest.mark.asyncio
async def test_vendor_stability_evaluates_with_motor_like_db():
    svc = StableVendorService(MotorLikeDB(), vendor_intel_service=_VendorIntel())

    result = await svc.evaluate_vendor_stability("ATSLOGI")

    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_auto_post_enrichment_does_not_truth_test_db():
    from services import auto_post_service

    db = MotorLikeDB()
    db.vendor_intelligence_profiles = _Coll({"stable_vendor_flag": True, "stable_vendor_score": 0.9})
    doc = {"vendor_canonical": "ATSLOGI"}

    result = await auto_post_service.attempt_auto_post("doc-1", doc, db, bc_service=None)

    assert doc["stable_vendor_flag"] is True
    assert result is not None
