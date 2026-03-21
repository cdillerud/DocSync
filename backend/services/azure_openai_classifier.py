"""
GPI Document Hub - Azure OpenAI Classifier

Fallback classifier that uses Azure OpenAI Chat Completions API
when Gemini is unavailable or returns low confidence.

Configuration (all optional — if unset, fallback is silently skipped):
    AZURE_OPENAI_ENDPOINT   – e.g. https://myresource.openai.azure.com
    AZURE_OPENAI_KEY        – API key for the Azure OpenAI resource
    AZURE_OPENAI_DEPLOYMENT – deployment name, e.g. gpt-4o
"""

import json
import logging
import os
from typing import Dict, Any

import httpx

logger = logging.getLogger(__name__)

# Read config once at import time
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_API_VERSION = "2024-02-01"


def is_azure_configured() -> bool:
    """Return True only when all required Azure OpenAI vars are present."""
    return bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and AZURE_OPENAI_DEPLOYMENT)


async def classify_document_with_azure_openai(
    text: str,
    file_name: str,
) -> Dict[str, Any]:
    """Classify a document using Azure OpenAI Chat Completions.

    Parameters
    ----------
    text : str
        Raw text extracted from the document (OCR / pypdf).
    file_name : str
        Original filename — useful for heuristic hints.

    Returns
    -------
    dict
        Same shape as the Gemini classifier:
        ``{suggested_job_type, confidence, extracted_fields, reasoning, model, ...}``
    """
    if not is_azure_configured():
        return {
            "error": "Azure OpenAI not configured",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
        }

    if not text or not text.strip():
        return {
            "error": "No text provided for Azure classification",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
        }

    # Import the shared system prompt from document_intel_helpers
    from services.document_intel_helpers import _CLASSIFY_SYSTEM_PROMPT

    # Truncate to a safe token budget (~12k chars ≈ 3k tokens)
    truncated_text = text[:12000]

    url = (
        f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{AZURE_OPENAI_DEPLOYMENT}/chat/completions"
        f"?api-version={AZURE_API_VERSION}"
    )

    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_KEY,
    }

    body = {
        "messages": [
            {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Please analyze this business document (filename: {file_name}).\n"
                    "Classify the document and extract all relevant fields. "
                    "Also extract routing fields: is_international, is_tooling, "
                    "is_storage_handling, is_credit_memo, is_dunnage, freight_direction. "
                    "Respond with JSON only.\n\n"
                    f"--- DOCUMENT TEXT ---\n{truncated_text}\n--- END ---"
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Strip markdown fences if present
        if content.strip().startswith("```"):
            lines = content.strip().split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                if line.startswith("```") and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            content = "\n".join(json_lines)

        result = json.loads(content)
        extracted = result.get("extracted_fields", {})

        logger.info(
            "[AzureOpenAI] classification result — doc_type=%s confidence=%s fields=%d",
            result.get("document_type"), result.get("confidence"), len(extracted),
        )

        return {
            "suggested_job_type": result.get("document_type", "Unknown"),
            "confidence": float(result.get("confidence", 0.0)),
            "extracted_fields": extracted,
            "reasoning": result.get("reasoning", ""),
            "model": f"azure-openai/{AZURE_OPENAI_DEPLOYMENT}",
        }

    except httpx.HTTPStatusError as he:
        logger.error("[AzureOpenAI] HTTP %s: %s", he.response.status_code, he.response.text[:300])
        return {
            "error": f"Azure OpenAI HTTP {he.response.status_code}",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
        }
    except Exception as e:
        logger.error("[AzureOpenAI] classification failed for '%s': %s", file_name, str(e))
        return {
            "error": str(e),
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
        }
