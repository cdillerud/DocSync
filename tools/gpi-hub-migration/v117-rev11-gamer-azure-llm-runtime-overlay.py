from __future__ import annotations

from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def replace_once(raw: str, old: str, new: str, label: str) -> str:
    require(old in raw, f"{label} anchor missing")
    return raw.replace(old, new, 1)


def patch_ap_routing(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    raw = replace_once(
        raw,
        'EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")',
        'AP_ROUTING_LLM_SOURCE = os.environ.get("AP_ROUTING_LLM_SOURCE", "gamer_azure").strip().lower()',
        "REV11 AP source constant",
    )

    old_sender = '''async def _default_llm_send(prompt: str, model: str) -> str:
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    provider = _provider_for_model(model)
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ap-route-{uuid.uuid4()}",
        system_message=(
            "You make bounded Accounts Payable routing predictions from supplied evidence. "
            "Return valid JSON only. Never invent routes outside the supplied contract."
        ),
    ).with_model(provider, model)
    return await chat.send_message(UserMessage(text=prompt))
'''
    new_sender = '''async def _default_llm_send(prompt: str, model: str) -> str:
    provider = _provider_for_model(model)
    if provider != "openai":
        raise RuntimeError(
            f"Gamer Azure AP routing supports the selected OpenAI deployment only: provider={provider}"
        )
    if AP_ROUTING_LLM_SOURCE != "gamer_azure":
        raise RuntimeError(
            "AP routing LLM source must be gamer_azure; "
            f"configured={AP_ROUTING_LLM_SOURCE or '<empty>'}"
        )

    from services.gamer_azure_llm_service import gamer_azure_text_completion

    return await gamer_azure_text_completion(
        prompt,
        model=model,
        system_message=(
            "You make bounded Accounts Payable routing predictions from supplied evidence. "
            "Return valid JSON only. Never invent routes outside the supplied contract."
        ),
    )
'''
    raw = replace_once(raw, old_sender, new_sender, "REV11 AP Gamer Azure sender")

    require("emergentintegrations" not in raw, "AP routing still imports Emergent after REV11")
    require("EMERGENT_LLM_KEY" not in raw, "AP routing still depends on EMERGENT_LLM_KEY")
    require('AP_ROUTING_LLM_SOURCE != "gamer_azure"' in raw, "AP source fail-closed guard missing")
    require(
        'DEFAULT_AUTO_ROUTE_THRESHOLD = float(os.environ.get("AP_ROUTING_AUTO_THRESHOLD", "0.92"))'
        in raw,
        "auto-route threshold changed during REV11",
    )
    require(
        'DEFAULT_REVIEW_THRESHOLD = float(os.environ.get("AP_ROUTING_REVIEW_THRESHOLD", "0.70"))'
        in raw,
        "review threshold changed during REV11",
    )

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def patch_supporting_refs(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")

    raw = replace_once(
        raw,
        'EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")',
        'SUPPORTING_LLM_SOURCE = os.environ.get("DOC_BUNDLE_SUPPORTING_LLM_SOURCE", "gamer_azure").strip().lower()',
        "REV11 supporting source constant",
    )
    raw = replace_once(
        raw,
        'DEFAULT_MODEL = os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gemini-2.5-pro")',
        'DEFAULT_MODEL = os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gpt-5.6-sol")',
        "REV11 supporting Azure deployment default",
    )

    old_provider = '''def _supporting_provider_for_model(model: str) -> str:
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
    new_provider = '''def _supporting_provider_for_model(model: str) -> str:
    selected_model = str(model or "").strip()
    configured = str(os.environ.get("DOC_BUNDLE_SUPPORTING_PROVIDER") or "").strip().lower()
    if selected_model != "gpt-5.6-sol":
        raise RuntimeError(
            "Gamer Azure supporting-reference extraction requires deployment gpt-5.6-sol: "
            f"model={selected_model or '<empty>'}"
        )
    if configured and configured != "openai":
        raise RuntimeError(
            "supporting-reference provider/model mismatch: "
            f"model={selected_model}; expected_provider=openai; configured_provider={configured}"
        )
    if SUPPORTING_LLM_SOURCE != "gamer_azure":
        raise RuntimeError(
            "supporting-reference LLM source must be gamer_azure; "
            f"configured={SUPPORTING_LLM_SOURCE or '<empty>'}"
        )
    return "openai"
'''
    raw = replace_once(raw, old_provider, new_provider, "REV11 supporting Azure provider")

    old_block = '''        if temp_pdf and llm_enabled and EMERGENT_LLM_KEY:
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

                chat = LlmChat(
                    api_key=EMERGENT_LLM_KEY,
                    session_id=f"supporting-refs-{uuid.uuid4()}",
                    system_message=(
                        "Extract labeled business references from supporting pages only. "
                        "Do not classify the document and do not infer unlabeled numbers. Return JSON only."
                    ),
                ).with_model(_supporting_provider_for_model(model), model)
                file_content = FileContentWithMimeType(
                    file_path=temp_pdf,
                    mime_type="application/pdf",
                )
                prompt = (
                    f"Primary document type is already locked as {primary_document_type}. "
                    "These are supporting pages 2 onward. Extract only explicitly supported references. "
                    "Preserve labels distinctly; never map a generic Reference # into BOL/shipment unless the page labels it that way. "
                    "Return JSON with arrays of objects {value,page,label} for: "
                    + ", ".join(_REFERENCE_FIELDS)
                    + ". JSON only."
                )
                raw = await chat.send_message(UserMessage(text=prompt, file_contents=[file_content]))
                parsed = json.loads(_strip_json_fence(raw))
                model_refs = _normalize_model_refs(parsed)
            except Exception as exc:
'''
    new_block = '''        if temp_pdf and llm_enabled:
            try:
                _supporting_provider_for_model(model)
                from services.gamer_azure_llm_service import gamer_azure_pdf_completion

                prompt = (
                    f"Primary document type is already locked as {primary_document_type}. "
                    "These are supporting pages 2 onward. Extract only explicitly supported references. "
                    "Preserve labels distinctly; never map a generic Reference # into BOL/shipment unless the page labels it that way. "
                    "Return JSON with arrays of objects {value,page,label} for: "
                    + ", ".join(_REFERENCE_FIELDS)
                    + ". JSON only."
                )
                response_text = await gamer_azure_pdf_completion(
                    temp_pdf,
                    prompt=prompt,
                    model=model,
                    system_message=(
                        "Extract labeled business references from supporting pages only. "
                        "Do not classify the document and do not infer unlabeled numbers. Return JSON only."
                    ),
                )
                parsed = json.loads(_strip_json_fence(response_text))
                model_refs = _normalize_model_refs(parsed)
            except Exception as exc:
'''
    raw = replace_once(raw, old_block, new_block, "REV11 supporting Gamer Azure sender")

    require("emergentintegrations" not in raw, "supporting refs still import Emergent after REV11")
    require("EMERGENT_LLM_KEY" not in raw, "supporting refs still depend on EMERGENT_LLM_KEY")
    require(
        'os.environ.get("DOC_BUNDLE_SUPPORTING_MODEL", "gpt-5.6-sol")' in raw,
        "REV11 supporting default deployment missing",
    )
    require(
        'SUPPORTING_LLM_SOURCE != "gamer_azure"' in raw,
        "supporting source fail-closed guard missing",
    )

    compile(raw, str(path), "exec")
    path.write_text(raw, encoding="utf-8", newline="\n")


def apply(root: str) -> None:
    base = Path(root)
    ap = base / "backend/services/ap_routing_decision_service.py"
    support = base / "backend/services/document_bundle_reference_service.py"

    for required in (ap, support):
        require(required.is_file(), f"missing REV11 patch target: {required}")

    patch_ap_routing(ap)
    patch_supporting_refs(support)

    print("V117_REV11_LLM_SOURCE=GAMER_AZURE")
    print("V117_REV11_EMERGENT_RUNTIME_DEPENDENCY=REMOVED")
    print("V117_REV11_AP_ROUTING_SOURCE=GAMER_AZURE")
    print("V117_REV11_SUPPORTING_REF_SOURCE=GAMER_AZURE")
    print("V117_REV11_AZURE_AUTH=MANAGED_IDENTITY")
    print("V117_REV11_AZURE_ENDPOINT=GAMERLLM")
    print("V117_REV11_AUTHORITY_THRESHOLDS=UNCHANGED")
    print("V117_REV11_PRODUCTION_MUTATION=NONE")


if __name__ == "__main__":
    import sys

    require(len(sys.argv) == 2, "usage: overlay.py <candidate-root>")
    apply(sys.argv[1])
