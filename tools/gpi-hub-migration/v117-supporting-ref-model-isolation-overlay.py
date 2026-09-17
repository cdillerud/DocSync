from __future__ import annotations

from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def apply(path: str) -> None:
    target = Path(path)
    raw = target.read_text(encoding="utf-8")

    old_defaults = '''EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_MODEL = os.environ.get("AP_ROUTING_MODEL", "gemini-2.5-pro")
MAX_SUPPORTING_PAGES = int(os.environ.get("DOC_BUNDLE_SUPPORTING_MAX_PAGES", "4"))
'''
    new_defaults = '''EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
SUPPORTED_SUPPORTING_MODEL_PROVIDERS = {
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
    "gpt-5.6-sol": "openai",
    "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic",
}
DEFAULT_MODEL = os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gemini-2.5-pro")
MAX_SUPPORTING_PAGES = int(os.environ.get("DOC_BUNDLE_SUPPORTING_MAX_PAGES", "4"))


def _supporting_provider_for_model(model: str) -> str:
    selected_model = str(model or "").strip()
    provider = SUPPORTED_SUPPORTING_MODEL_PROVIDERS.get(selected_model)
    configured = str(os.environ.get("DOC_BUNDLE_SUPPORTING_PROVIDER") or "").strip().lower()
    if not provider:
        if not configured:
            raise RuntimeError(
                f"unsupported supporting-reference model/provider pair: model={selected_model or '<empty>'}"
            )
        provider = configured
    if configured and configured != provider:
        raise RuntimeError(
            "supporting-reference provider/model mismatch: "
            f"model={selected_model}; expected_provider={provider}; configured_provider={configured}"
        )
    return provider
'''
    require(old_defaults in raw, "supporting-reference model default anchor missing")
    raw = raw.replace(old_defaults, new_defaults, 1)

    old_sender = ').with_model("gemini", model)'
    new_sender = ').with_model(_supporting_provider_for_model(model), model)'
    require(old_sender in raw, "supporting-reference hardcoded provider anchor missing")
    raw = raw.replace(old_sender, new_sender, 1)

    require('os.environ.get("AP_ROUTING_MODEL"' not in raw,
            "supporting-reference service still coupled to AP_ROUTING_MODEL")
    require('os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gemini-2.5-pro")' in raw,
            "supporting-reference dedicated model default missing")

    compile(raw, str(target), "exec")
    target.write_text(raw, encoding="utf-8", newline="\n")

    print("V117_SUPPORTING_REF_MODEL_ISOLATION=PASS")
    print("V117_SUPPORTING_REF_DEFAULT_PROVIDER=gemini")
    print("V117_SUPPORTING_REF_DEFAULT_MODEL=gemini-2.5-pro")
    print("V117_SUPPORTING_REF_AP_ROUTING_MODEL_COUPLING=REMOVED")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <document_bundle_reference_service.py>")
    apply(sys.argv[1])
