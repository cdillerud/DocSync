import pytest

import services.email_service as email_module
from services.email_service import (
    EmailMessage,
    MicrosoftGraphEmailProvider,
)


class FakeResponse:
    def __init__(
        self,
        status_code,
        payload=None,
        text="",
        headers=None,
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.calls.append({
            "url": url,
            **kwargs,
        })

        if url.endswith("/oauth2/v2.0/token"):
            return FakeResponse(
                200,
                {"access_token": "test-token"},
            )

        return FakeResponse(
            202,
            headers={"request-id": "graph-request-id"},
        )


@pytest.mark.asyncio
async def test_graph_provider_sends_mail(monkeypatch):
    client = FakeAsyncClient()

    monkeypatch.setattr(
        email_module.httpx,
        "AsyncClient",
        lambda timeout: client,
    )

    provider = MicrosoftGraphEmailProvider(
        client_id="client-id",
        client_secret="client-secret",
        tenant_id="tenant-id",
        sender="hub-ap-intake@gamerpackaging.com",
    )

    result = await provider.send(
        EmailMessage(
            to=["cdillerud@gamerpackaging.com"],
            subject="Cache alert test",
            html_body="<p>Test</p>",
        )
    )

    assert result.success is True
    assert result.provider == "microsoft_graph"
    assert result.message_id == "graph-request-id"
    assert len(client.calls) == 2

    send_call = client.calls[1]

    assert send_call["url"].endswith(
        "/users/hub-ap-intake@gamerpackaging.com/sendMail"
    )
    assert send_call["json"]["message"]["toRecipients"] == [{
        "emailAddress": {
            "address": "cdillerud@gamerpackaging.com",
        }
    }]
    assert send_call["json"]["saveToSentItems"] is True


@pytest.mark.asyncio
async def test_graph_provider_requires_sender():
    provider = MicrosoftGraphEmailProvider(
        client_id="client-id",
        client_secret="client-secret",
        tenant_id="tenant-id",
        sender="",
    )

    result = await provider.send(
        EmailMessage(
            to=["cdillerud@gamerpackaging.com"],
            subject="Test",
            html_body="<p>Test</p>",
        )
    )

    assert result.success is False
    assert "EMAIL_GRAPH_SENDER" in result.error
