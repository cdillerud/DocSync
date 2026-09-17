import asyncio
import os
import sys
import tempfile
import types

import pytest

from services import document_bundle_reference_service as svc


def _install_fake_emergent(monkeypatch, captured):
    root = types.ModuleType("emergentintegrations")
    llm = types.ModuleType("emergentintegrations.llm")
    chat = types.ModuleType("emergentintegrations.llm.chat")

    class FakeFileContentWithMimeType:
        def __init__(self, **kwargs):
            captured["file"] = kwargs

    class FakeUserMessage:
        def __init__(self, **kwargs):
            captured["message"] = kwargs

    class FakeLlmChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_model(self, provider, model):
            captured["provider"] = provider
            captured["model"] = model
            return self

        async def send_message(self, message):
            return '{"po_numbers":[],"order_numbers":[],"bol_numbers":[],"shipment_numbers":[],"receipt_numbers":[],"reference_numbers":[],"pro_numbers":[],"load_numbers":[]}'

    chat.LlmChat = FakeLlmChat
    chat.UserMessage = FakeUserMessage
    chat.FileContentWithMimeType = FakeFileContentWithMimeType
    llm.chat = chat
    root.llm = llm

    monkeypatch.setitem(sys.modules, "emergentintegrations", root)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm", llm)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat", chat)


def test_supporting_default_isolated_from_ap_routing_model():
    assert os.environ.get("AP_ROUTING_MODEL") == "gpt-5.6-sol"
    assert svc.DEFAULT_MODEL == os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gemini-2.5-pro")
    assert svc.DEFAULT_MODEL == "gemini-2.5-pro"


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gemini-2.5-pro", "gemini"),
        ("gemini-2.5-flash", "gemini"),
        ("gpt-5.6-sol", "openai"),
        ("claude-opus-4-6", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
    ],
)
def test_supporting_provider_mapping(monkeypatch, model, provider):
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)
    assert svc._supporting_provider_for_model(model) == provider


def test_supporting_provider_mismatch_fails_closed(monkeypatch):
    monkeypatch.setenv("DOC_BUNDLE_SUPPORTING_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="provider/model mismatch"):
        svc._supporting_provider_for_model("gemini-2.5-pro")


def test_unknown_supporting_model_without_provider_fails_closed(monkeypatch):
    monkeypatch.delenv("DOC_BUNDLE_SUPPORTING_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="unsupported supporting-reference model/provider pair"):
        svc._supporting_provider_for_model("not-a-real-model")


def test_supporting_extractor_keeps_gemini_default_when_router_is_gpt(monkeypatch):
    captured = {}
    _install_fake_emergent(monkeypatch, captured)
    monkeypatch.setattr(svc, "EMERGENT_LLM_KEY", "unit-test-key")
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

    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-2.5-pro"
    assert result["model_error"] is None
