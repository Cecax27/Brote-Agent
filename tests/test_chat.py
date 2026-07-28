from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from app.agent.loop import UpstreamError
from app.supabase.context import ContextBundle


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_returns_reply(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = "Hola, ¿cómo puedo ayudarte con tus plantas?"
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat", json={"message": "Tengo una monstera"}, headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert data["reply"] == "Hola, ¿cómo puedo ayudarte con tus plantas?"
    mock_gemini.assert_called_once()


@pytest.mark.asyncio
async def test_chat_empty_message_returns_422(
    client: AsyncClient, mock_auth_verify: AsyncMock, auth_headers: dict
) -> None:
    mock_auth_verify.return_value = {"id": "test-user-id"}

    response = await client.post("/chat", json={"message": ""}, headers=auth_headers)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_chat_missing_message_returns_422(
    client: AsyncClient, mock_auth_verify: AsyncMock, auth_headers: dict
) -> None:
    mock_auth_verify.return_value = {"id": "test-user-id"}

    response = await client.post("/chat", json={}, headers=auth_headers)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data


def test_chat_upstream_error_returns_502(
    sync_client: TestClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    auth_headers: dict,
) -> None:
    mock_gemini.side_effect = UpstreamError(
        "El servicio de IA no respondió. Inténtalo de nuevo en un momento."
    )
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = sync_client.post("/chat", json={"message": "test"}, headers=auth_headers)

    assert response.status_code == 502
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "UPSTREAM_ERROR"
    assert "El servicio" in data["error"]["message"]


def test_chat_unexpected_error_returns_500(
    sync_client: TestClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    auth_headers: dict,
) -> None:
    mock_gemini.side_effect = Exception("Unexpected internal failure")
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = sync_client.post("/chat", json={"message": "test"}, headers=auth_headers)

    assert response.status_code == 500
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INTERNAL_ERROR"
