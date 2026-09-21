import asyncio
import os
import tempfile

import pytest

from services import document_bundle_reference_service as svc
from services import gamer_azure_llm_service as azure_llm


def test_supporting_default_is_gamer_azure_and_isolated_from_router_env():
    assert svc.DEFAULT_MODEL == os.environ.get(
        "DOC_BUNDLE_SUPPORTING_MODEL",
        "gpt-5.6-sol",
    )
    assert svc.DEFAULT_MODEL == "gpt-5.6-sol"
    assert svc.SUPPORTING_LLM_SOURCE == "gamer_azure"
    assert not hasattr(svc, "EMERGENT_LLM_KEY")


def test_supporting_provider_is_openai_for_gamer_azure(monkeypatch):
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)
    monkeypatch.setattr(svc, "SUPPORTING_LLM_SOURCE", "gamer_azure")
    assert svc._supporting_provider_for_model("gpt-5.6-sol") == "openai"


def test_supporting_provider_mismatch_fails_closed(monkeypatch):
    monkeypatch.setenv("DOC_BUNDLE_SUPPORTING_PROVIDER", "gemini")
    monkeypatch.setattr(svc, "SUPPORTING_LLM_SOURCE", "gamer_azure")
    with pytest.raises(RuntimeError, match="provider/model mismatch"):
        svc._supporting_provider_for_model("gpt-5.6-sol")


def test_unknown_supporting_model_fails_closed(monkeypatch):
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)
    monkeypatch.setattr(svc, "SUPPORTING_LLM_SOURCE", "gamer_azure")
    with pytest.raises(RuntimeError, match="requires deployment gpt-5.6-sol"):
        svc._supporting_provider_for_model("not-a-real-model")


def test_supporting_source_mismatch_fails_closed(monkeypatch):
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)
    monkeypatch.setattr(svc, "SUPPORTING_LLM_SOURCE", "emergent")
    with pytest.raises(RuntimeError, match="source must be gamer_azure"):
        svc._supporting_provider_for_model("gpt-5.6-sol")


def test_supporting_extractor_uses_gamer_azure_pdf_transport(monkeypatch):
    captured = {}

    async def fake_pdf_completion(pdf_path, *, prompt, model, system_message):
        captured["pdf_path"] = pdf_path
        captured["prompt"] = prompt
        captured["model"] = model
        captured["system_message"] = system_message
        return (
            '{"po_numbers":[],"order_numbers":[],"bol_numbers":[],'
            '"shipment_numbers":[],"receipt_numbers":[],"reference_numbers":[],'
            '"pro_numbers":[],"load_numbers":[]}'
        )

    monkeypatch.setattr(azure_llm, "gamer_azure_pdf_completion", fake_pdf_completion)
    monkeypatch.setattr(svc, "SUPPORTING_LLM_SOURCE", "gamer_azure")
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)

    temp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temp.close()

    def fake_extract(_file_path):
        return 2, [{"page": 2, "text": "Reference # ABC123"}], temp.name

    monkeypatch.setattr(svc, "_extract_page_text_and_pdf", fake_extract)

    result = asyncio.run(
        svc.extract_supporting_references(
            "placeholder.pdf",
            "placeholder.pdf",
            primary_document_type="AP_Invoice",
            primary_fields={},
        )
    )

    assert captured["model"] == "gpt-5.6-sol"
    assert "supporting pages 2 onward" in captured["prompt"]
    assert "supporting pages only" in captured["system_message"]
    assert result["model_error"] is None
