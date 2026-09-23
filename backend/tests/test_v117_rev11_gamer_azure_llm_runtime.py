import asyncio
import os

import pytest

from services import gamer_azure_llm_service as svc


def test_rev11_endpoint_defaults_to_gamerllm_openai_v1(monkeypatch):
    monkeypatch.delenv("GAMER_AZURE_OPENAI_ENDPOINT", raising=False)
    assert svc.gamer_azure_endpoint() == (
        "https://gamerllm.openai.azure.com/openai/v1/"
    )


def test_rev11_endpoint_rejects_non_gamer_host(monkeypatch):
    monkeypatch.setenv(
        "GAMER_AZURE_OPENAI_ENDPOINT",
        "https://api.openai.com/v1",
    )
    with pytest.raises(RuntimeError, match="approved GamerLLM Azure host"):
        svc.gamer_azure_endpoint()


def test_rev11_default_deployment_is_gpt56_sol(monkeypatch):
    monkeypatch.delenv("GAMER_AZURE_OPENAI_DEPLOYMENT", raising=False)
    assert svc.gamer_azure_deployment("gpt-5.6-sol") == "gpt-5.6-sol"


def test_rev11_response_text_extraction_handles_rest_shape():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"ok":true}',
                    }
                ],
            }
        ]
    }
    assert svc._response_output_text(payload) == '{"ok":true}'


def test_rev11_text_completion_posts_selected_deployment(monkeypatch):
    captured = {}

    async def fake_request(payload):
        captured.update(payload)
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "OK",
                        }
                    ]
                }
            ]
        }

    monkeypatch.setattr(svc, "_responses_request", fake_request)
    result = asyncio.run(
        svc.gamer_azure_text_completion(
            "hello",
            model="gpt-5.6-sol",
            system_message="system",
        )
    )

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["input"] == "hello"
    assert captured["store"] is False
    assert result == "OK"


def test_rev11_transport_has_no_emergent_key_dependency():
    source = open(svc.__file__, "r", encoding="utf-8").read()
    assert "EMERGENT_LLM_KEY" not in source
    assert "emergentintegrations" not in source

def test_rev11_document_completion_posts_pdf_to_responses(monkeypatch, tmp_path):
    captured = {}

    async def fake_request(payload):
        captured.update(payload)
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"document_type":"AP_Invoice","confidence":0.9,"extracted_fields":{}}',
                        }
                    ]
                }
            ]
        }

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% synthetic transport payload\n")
    monkeypatch.setattr(svc, "_responses_request", fake_request)

    result = asyncio.run(
        svc.gamer_azure_document_completion(
            str(pdf),
            prompt="classify",
            model="gpt-5.6-sol",
            system_message="json only",
        )
    )

    content = captured["input"][0]["content"]
    assert captured["model"] == "gpt-5.6-sol"
    assert content[0]["type"] == "input_file"
    assert content[0]["filename"] == "sample.pdf"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert result.startswith('{"document_type":"AP_Invoice"')


def test_rev11_document_intelligence_has_no_emergent_or_key_fallback():
    from services import document_intel_helpers as helpers

    source = open(helpers.__file__, "r", encoding="utf-8").read()
    assert "EMERGENT_LLM_KEY" not in source
    assert "emergentintegrations" not in source
    assert "azure_openai_classifier" not in source
    assert 'DOCUMENT_INTEL_LLM_SOURCE != "gamer_azure"' in source
    assert "gamer_azure_document_completion" in source

