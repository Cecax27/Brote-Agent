from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_returns_reply(client: AsyncClient, mock_gemini: AsyncMock) -> None:
    mock_gemini.return_value = "Hola, ¿cómo puedo ayudarte con tus plantas?"

    response = await client.post("/chat", json={"message": "Tengo una monstera"})

    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert data["reply"] == "Hola, ¿cómo puedo ayudarte con tus plantas?"
    mock_gemini.assert_called_once()


@pytest.mark.asyncio
async def test_chat_empty_message_returns_422(client: AsyncClient) -> None:
    response = await client.post("/chat", json={"message": ""})
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_chat_missing_message_returns_422(client: AsyncClient) -> None:
    response = await client.post("/chat", json={})
    assert response.status_code == 422
    data = response.json()
    assert "error" in data


def test_chat_gemini_error_returns_500(sync_client: TestClient, mock_gemini: AsyncMock) -> None:
    mock_gemini.side_effect = Exception("Gemini API error")

    response = sync_client.post("/chat", json={"message": "test"})

    assert response.status_code == 500
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INTERNAL_ERROR"
    assert "OpenAI" not in data["error"]["message"]
