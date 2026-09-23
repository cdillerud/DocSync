"""
Central LLM model configuration for GPI-Hub.

This keeps model names out of hardcoded AI/LLM service logic.

Important:
- This does not change prompts.
- This does not change extraction logic.
- This does not change classification logic.
- This does not change BC validation.
- This does not change SharePoint behavior.
"""

import os

# --- Stage 1 of the Gemini -> Azure OpenAI migration -------------------
# Default provider is now "azure" (GPI's own GamerLLM Azure OpenAI
# resource). Set GPI_LLM_PROVIDER=gemini in .env to revert to the old
# Gemini path -- still present in document_intel_helpers.py's
# _call_llm_for_extraction as of Stage 1; full removal is Stage 2.
DEFAULT_LLM_PROVIDER = "azure"
DEFAULT_LLM_MODEL = "gemini-2.5-pro"  # only consulted when provider == "gemini"


def get_llm_provider() -> str:
    return os.getenv("GPI_LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip() or DEFAULT_LLM_PROVIDER


def get_llm_model() -> str:
    """Model/deployment name for whichever provider is active.

    For "azure" this is the Azure OpenAI DEPLOYMENT name, sourced from
    AZURE_OPENAI_DEPLOYMENT so there's one place -- not two -- that names
    the deployment (avoids GPI_LLM_MODEL and AZURE_OPENAI_DEPLOYMENT
    silently drifting apart).
    """
    provider = get_llm_provider()
    if provider == "azure":
        from services.azure_openai_classifier import AZURE_OPENAI_DEPLOYMENT
        return AZURE_OPENAI_DEPLOYMENT
    return os.getenv("GPI_LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL


def get_llm_display_name() -> str:
    return get_llm_model()


def get_llm_method(prefix: str = "llm") -> str:
    return f"{prefix}:{get_llm_model()}"
