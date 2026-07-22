import pytest

from services.ai_classifier import VALID_DOC_TYPES
from services.classification_pipeline import (
    StageStatus,
    stage_route,
    stage_validate,
)
from services.document_intel_helpers import (
    _CLASSIFY_SYSTEM_PROMPT,
)


def test_graphics_artwork_is_allowed():
    assert "GRAPHICS_ARTWORK" in VALID_DOC_TYPES
    assert "Graphics_Artwork" in _CLASSIFY_SYSTEM_PROMPT
    assert "slit width" in _CLASSIFY_SYSTEM_PROMPT.lower()
    assert "human confirmation" in _CLASSIFY_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_graphics_artwork_skips_bc_validation():
    result = await stage_validate(
        "Graphics_Artwork",
        {},
    )

    assert result.status == StageStatus.PASSED
    assert result.data["validation_results"]["skipped"] is True


def test_graphics_artwork_always_requires_human_review():
    result = stage_route(
        classification_confidence=0.99,
        validation_results={"all_passed": True},
        extracted_fields={},
        doc_type="Graphics_Artwork",
        job_config={},
    )

    assert result.status == StageStatus.PASSED
    assert result.data["automation_decision"] == "needs_review"
    assert result.data["readiness_status"] == "needs_review"
