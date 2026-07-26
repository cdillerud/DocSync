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

DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_LLM_MODEL = "gemini-2.5-pro"


def get_llm_provider() -> str:
    return os.getenv("GPI_LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip() or DEFAULT_LLM_PROVIDER


def get_llm_model() -> str:
    return os.getenv("GPI_LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL


def get_llm_display_name() -> str:
    return get_llm_model()


def get_llm_method(prefix: str = "llm") -> str:
    return f"{prefix}:{get_llm_model()}"
