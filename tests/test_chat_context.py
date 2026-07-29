from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.agent.loop import UpstreamError
from app.supabase.context import ContextBundle, DeepPlantContext, PlantSummary


@pytest.mark.asyncio
async def test_chat_passes_context_to_gemini(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "Tu Monstera está bien."}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    await client.post(
        "/chat",
        json={"message": "¿Cómo está mi planta?"},
        headers=auth_headers,
    )

    call_args = mock_gemini.call_args
    assert call_args is not None
    context_value = call_args.kwargs.get("context")
    assert context_value is not None


@pytest.mark.asyncio
async def test_chat_uses_deep_mode_when_plant_id_set(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "Tu planta está creciendo muy bien."}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(
        deep=DeepPlantContext(
            plant=PlantSummary(
                id="plant-123",
                name="Monstera",
                species="Monstera deliciosa",
                last_watered_at="2025-01-15",
                next_due_at="2025-01-22",
            )
        )
    )

    await client.post(
        "/chat",
        json={"message": "¿Cómo está mi Monstera?", "plant_id": "plant-123"},
        headers=auth_headers,
    )

    mock_supabase_context.assert_called_once()
    assert mock_supabase_context.call_args[0][1] == "plant-123"


@pytest.mark.asyncio
async def test_chat_uses_light_mode_when_no_plant_id(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "Tienes 3 plantas que necesitan atención."}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    await client.post(
        "/chat",
        json={"message": "¿Qué necesita atención hoy?"},
        headers=auth_headers,
    )

    mock_supabase_context.assert_called_once()
    assert mock_supabase_context.call_args[0][1] is None


@pytest.mark.asyncio
async def test_chat_supabase_failure_returns_502(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.side_effect = UpstreamError(
        "El servicio de datos no respondió. Inténtalo de nuevo en un momento."
    )

    response = await client.post(
        "/chat",
        json={"message": "Hola"},
        headers=auth_headers,
    )

    assert response.status_code == 502
    data = response.json()
    assert data["error"]["code"] == "UPSTREAM_ERROR"
    mock_gemini.assert_not_called()


@pytest.mark.asyncio
async def test_chat_context_sets_data_minimization_bounds(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "Todo bien."}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    await client.post(
        "/chat",
        json={"message": "test"},
        headers=auth_headers,
    )

    call_kwargs = mock_supabase_context.call_args.kwargs
    assert call_kwargs["max_plants"] <= 20
    assert call_kwargs["max_entries"] <= 10


@pytest.mark.asyncio
async def test_chat_off_topic_refusal_still_works(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": (
            "Me encantaría poder ayudarte con eso, pero yo soy Flora, "
            "solo sé de plantas. ¿Tienes alguna planta de la que quieras hablarme?"
        )
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat",
        json={"message": "¿Cuál es la capital de Francia?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "planta" in data["reply"].lower() or "plantas" in data["reply"].lower()


@pytest.mark.asyncio
async def test_chat_reply_still_in_spanish(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "¡Claro! Las suculentas necesitan mucha luz y cariño."}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat",
        json={"message": "How do I care for a succulent?"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert any(
        char in data["reply"].lower() for char in ("\u00e1", "\u00e9", "\u00f3", "\u00fa", "\u00f1")
    )
