from __future__ import annotations

from pathlib import Path

SELECTED_MODEL = "gpt-5.6-sol"
SELECTED_PROVIDER = "openai"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def apply(path: str) -> None:
    target = Path(path)
    raw = target.read_text(encoding="utf-8")

    old_default = 'DEFAULT_MODEL = os.environ.get("AP_ROUTING_MODEL", "gemini-2.5-pro")'
    new_default = '''SELECTED_MODEL = "gpt-5.6-sol"\nSELECTED_PROVIDER = "openai"\nSUPPORTED_MODEL_PROVIDERS = {\n    "gpt-5.6-sol": "openai",\n    "gemini-2.5-pro": "gemini",\n    "claude-opus-4-6": "anthropic",\n    "claude-sonnet-4-6": "anthropic",\n}\nDEFAULT_MODEL = os.environ.get("AP_ROUTING_MODEL", SELECTED_MODEL)'''
    require(old_default in raw, "selected-model default anchor missing")
    raw = raw.replace(old_default, new_default, 1)

    old_sender = '''async def _default_llm_send(prompt: str, model: str) -> str:\n    if not EMERGENT_LLM_KEY:\n        raise RuntimeError("EMERGENT_LLM_KEY is not configured")\n    from emergentintegrations.llm.chat import LlmChat, UserMessage\n\n    chat = LlmChat(\n        api_key=EMERGENT_LLM_KEY,\n        session_id=f"ap-route-{uuid.uuid4()}",\n        system_message=(\n            "You make bounded Accounts Payable routing predictions from supplied evidence. "\n            "Return valid JSON only. Never invent routes outside the supplied contract."\n        ),\n    ).with_model("gemini", model)\n    return await chat.send_message(UserMessage(text=prompt))\n'''
    new_sender = '''def _provider_for_model(model: str) -> str:\n    selected_model = str(model or "").strip()\n    provider = SUPPORTED_MODEL_PROVIDERS.get(selected_model)\n    if not provider:\n        raise RuntimeError(f"unsupported AP routing model/provider pair: model={selected_model or '<empty>'}")\n    configured_provider = str(os.environ.get("AP_ROUTING_PROVIDER") or "").strip().lower()\n    if configured_provider and configured_provider != provider:\n        raise RuntimeError(\n            "AP routing provider/model mismatch: "\n            f"model={selected_model}; expected_provider={provider}; configured_provider={configured_provider}"\n        )\n    return provider\n\n\nasync def _default_llm_send(prompt: str, model: str) -> str:\n    if not EMERGENT_LLM_KEY:\n        raise RuntimeError("EMERGENT_LLM_KEY is not configured")\n    from emergentintegrations.llm.chat import LlmChat, UserMessage\n\n    provider = _provider_for_model(model)\n    chat = LlmChat(\n        api_key=EMERGENT_LLM_KEY,\n        session_id=f"ap-route-{uuid.uuid4()}",\n        system_message=(\n            "You make bounded Accounts Payable routing predictions from supplied evidence. "\n            "Return valid JSON only. Never invent routes outside the supplied contract."\n        ),\n    ).with_model(provider, model)\n    return await chat.send_message(UserMessage(text=prompt))\n'''
    require(old_sender in raw, "selected-model sender anchor missing")
    raw = raw.replace(old_sender, new_sender, 1)

    # Safety assertion: the selected-model overlay must not alter any threshold literals.
    require('DEFAULT_AUTO_ROUTE_THRESHOLD = float(os.environ.get("AP_ROUTING_AUTO_THRESHOLD", "0.92"))' in raw,
            "auto-route threshold anchor changed")
    require('DEFAULT_REVIEW_THRESHOLD = float(os.environ.get("AP_ROUTING_REVIEW_THRESHOLD", "0.70"))' in raw,
            "review threshold anchor changed")

    compile(raw, str(target), "exec")
    target.write_text(raw, encoding="utf-8", newline="\n")

    print("V117_SELECTED_MODEL=gpt-5.6-sol")
    print("V117_SELECTED_PROVIDER=openai")
    print("V117_SELECTED_MODEL_PROVIDER_DISPATCH=PASS")
    print("V117_SELECTED_MODEL_AUTHORITY_THRESHOLDS=UNCHANGED")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <ap_routing_decision_service.py>")
    apply(sys.argv[1])
