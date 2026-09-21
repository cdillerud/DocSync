import asyncio

import pytest

from services import ap_routing_decision_service as svc
from services import gamer_azure_llm_service as azure_llm


def test_selected_default_pair_is_gpt56_sol_openai_on_gamer_azure(monkeypatch):
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    assert svc.SELECTED_MODEL == "gpt-5.6-sol"
    assert svc.SELECTED_PROVIDER == "openai"
    assert svc.DEFAULT_MODEL == "gpt-5.6-sol"
    assert svc.AP_ROUTING_LLM_SOURCE == "gamer_azure"
    assert svc._provider_for_model("gpt-5.6-sol") == "openai"
    assert not hasattr(svc, "EMERGENT_LLM_KEY")


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gpt-5.6-sol", "openai"),
        ("gemini-2.5-pro", "gemini"),
        ("claude-opus-4-6", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
    ],
)
def test_provider_mapping_remains_deterministic(monkeypatch, model, provider):
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


def test_default_sender_uses_gamer_azure_transport(monkeypatch):
    captured = {}

    async def fake_completion(prompt, *, model, system_message):
        captured["prompt"] = prompt
        captured["model"] = model
        captured["system_message"] = system_message
        return (
            '{"proposed_route":"DO NOT PAY","confidence":1.0,"evidence":[],'
            '"reasoning_summary":"ok","bc_refs_used":[],"unresolved":[],'
            '"matched_example_ids":[]}'
        )

    monkeypatch.setattr(azure_llm, "gamer_azure_text_completion", fake_completion)
    monkeypatch.setattr(svc, "AP_ROUTING_LLM_SOURCE", "gamer_azure")
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)

    result = asyncio.run(svc._default_llm_send("hello", "gpt-5.6-sol"))

    assert captured["prompt"] == "hello"
    assert captured["model"] == "gpt-5.6-sol"
    assert "Accounts Payable routing predictions" in captured["system_message"]
    assert "proposed_route" in result


def test_default_sender_rejects_non_gamer_source(monkeypatch):
    monkeypatch.setattr(svc, "AP_ROUTING_LLM_SOURCE", "emergent")
    monkeypatch.delenv("AP_ROUTING_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="source must be gamer_azure"):
        asyncio.run(svc._default_llm_send("hello", "gpt-5.6-sol"))


def test_gamer_azure_deployment_mismatch_fails_closed(monkeypatch):
    monkeypatch.setenv("GAMER_AZURE_OPENAI_DEPLOYMENT", "gpt-5.6-sol")
    with pytest.raises(RuntimeError, match="deployment/model mismatch"):
        azure_llm.gamer_azure_deployment("gemini-2.5-pro")


def test_selected_model_overlay_does_not_change_authority_thresholds():
    assert svc.DEFAULT_AUTO_ROUTE_THRESHOLD == 0.92
    assert svc.DEFAULT_REVIEW_THRESHOLD == 0.70
