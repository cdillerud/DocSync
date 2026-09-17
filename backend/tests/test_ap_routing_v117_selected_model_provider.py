import asyncio
import sys
import types

import pytest

from services import ap_routing_decision_service as svc


def _install_fake_emergent(monkeypatch, captured):
    root = types.ModuleType("emergentintegrations")
    llm = types.ModuleType("emergentintegrations.llm")
    chat = types.ModuleType("emergentintegrations.llm.chat")

    class FakeUserMessage:
        def __init__(self, text):
            self.text = text

    class FakeLlmChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_model(self, provider, model):
            captured["provider"] = provider
            captured["model"] = model
            return self

        async def send_message(self, message):
            captured["message"] = message.text
            return '{"proposed_route":"DO NOT PAY","confidence":1.0,"evidence":[],"reasoning_summary":"ok","bc_refs_used":[],"unresolved":[],"matched_example_ids":[]}'

    chat.LlmChat = FakeLlmChat
    chat.UserMessage = FakeUserMessage
    llm.chat = chat
    root.llm = llm

    monkeypatch.setitem(sys.modules, "emergentintegrations", root)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm", llm)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat", chat)


def test_selected_default_pair_is_gpt56_sol_openai(monkeypatch):
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    assert svc.SELECTED_MODEL == "gpt-5.6-sol"
    assert svc.SELECTED_PROVIDER == "openai"
    assert svc.DEFAULT_MODEL == "gpt-5.6-sol"
    assert svc._provider_for_model("gpt-5.6-sol") == "openai"


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gpt-5.6-sol", "openai"),
        ("gemini-2.5-pro", "gemini"),
        ("claude-opus-4-6", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
    ],
)
def test_provider_mapping_is_deterministic(monkeypatch, model, provider):
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    assert svc._provider_for_model(model) == provider


def test_provider_model_mismatch_fails_closed(monkeypatch):
    monkeypatch.setenv("AP_ROUTING_PROVIDER", "gemini")
    with pytest.raises(RuntimeError, match="provider/model mismatch"):
        svc._provider_for_model("gpt-5.6-sol")


def test_unknown_model_fails_closed(monkeypatch):
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="unsupported AP routing model/provider pair"):
        svc._provider_for_model("not-a-real-model")


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gpt-5.6-sol", "openai"),
        ("gemini-2.5-pro", "gemini"),
        ("claude-sonnet-4-6", "anthropic"),
    ],
)
def test_default_sender_uses_resolved_provider(monkeypatch, model, provider):
    captured = {}
    _install_fake_emergent(monkeypatch, captured)
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    monkeypatch.setattr(svc, "EMERGENT_LLM_KEY", "unit-test-key")

    result = asyncio.run(svc._default_llm_send("hello", model))

    assert captured["provider"] == provider
    assert captured["model"] == model
    assert captured["message"] == "hello"
    assert "proposed_route" in result


def test_selected_model_overlay_does_not_change_authority_thresholds():
    assert svc.DEFAULT_AUTO_ROUTE_THRESHOLD == 0.92
    assert svc.DEFAULT_REVIEW_THRESHOLD == 0.70
