from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.supabase.context import ContextBundle, DeepPlantContext, PlantSummary


@pytest.mark.asyncio
async def test_chat_returns_proposed_action_when_gemini_proposes(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": "Tu Monstera necesita riego cada 7 días. ¿Quieres que lo configure?",
        "proposed_action": {
            "action_type": "create_watering_schedule",
            "plant_id": "plant-123",
            "title": "Riego semanal para Monstera",
            "summary_es": "Crear riego cada 7 días para tu Monstera",
            "payload": {
                "frequency_days": 7,
                "next_due_at": "2025-06-08T00:00:00Z",
            },
        },
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(
        deep=DeepPlantContext(
            plant=PlantSummary(
                id="plant-123",
                name="Monstera",
                species="Monstera deliciosa",
                last_watered_at="2025-06-01",
                next_due_at="2025-06-08",
            )
        )
    )

    response = await client.post(
        "/chat",
        json={"message": "¿Cada cuánto riego mi Monstera?", "plant_id": "plant-123"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert data["proposed_action"] is not None
    assert data["proposed_action"]["action_type"] == "create_watering_schedule"
    assert "confirm_token" in data["proposed_action"]


@pytest.mark.asyncio
async def test_chat_proposed_action_null_when_no_intent(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {"reply": "Hola, ¿cómo puedo ayudarte con tus plantas?"}
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat",
        json={"message": "Hola"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_action"] is None
    assert "reply" in data


@pytest.mark.asyncio
async def test_chat_proposed_action_null_on_unknown_action_type(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": "Claro.",
        "proposed_action": {
            "action_type": "delete_all_plants",
            "plant_id": "plant-1",
            "title": "X",
            "summary_es": "X",
            "payload": {},
        },
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat",
        json={"message": "Hola"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_action"] is None
    assert data["reply"] == "Claro."


@pytest.mark.asyncio
async def test_chat_proposed_action_null_on_plant_mismatch(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": "OK.",
        "proposed_action": {
            "action_type": "create_watering_schedule",
            "plant_id": "other-plant",
            "title": "Riego",
            "summary_es": "Riego",
            "payload": {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"},
        },
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    response = await client.post(
        "/chat",
        json={"message": "Hola", "plant_id": "plant-123"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_action"] is None


@pytest.mark.asyncio
async def test_chat_proposed_action_null_on_invalid_payload(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": "Bien.",
        "proposed_action": {
            "action_type": "create_watering_schedule",
            "plant_id": "plant-123",
            "title": "Riego",
            "summary_es": "Riego",
            "payload": {"frequency_days": 0},  # invalid: must be >= 1
        },
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(
        deep=DeepPlantContext(
            plant=PlantSummary(
                id="plant-123", name="M", species="S", last_watered_at=None, next_due_at=None
            )
        )
    )

    response = await client.post(
        "/chat",
        json={"message": "Riega", "plant_id": "plant-123"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_action"] is None


@pytest.mark.asyncio
async def test_chat_proposed_action_add_journal_entry(
    client: AsyncClient,
    mock_gemini: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    mock_gemini.return_value = {
        "reply": "¡Buen consejo! ¿Quieres guardarlo?",
        "proposed_action": {
            "action_type": "add_journal_entry",
            "plant_id": "plant-123",
            "title": "Guardar consejo",
            "summary_es": "Guardar este consejo en tu diario",
            "payload": {"content": "Regar solo cuando el sustrato esté seco"},
        },
    }
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(
        deep=DeepPlantContext(
            plant=PlantSummary(
                id="plant-123", name="M", species="S", last_watered_at=None, next_due_at=None
            )
        )
    )

    response = await client.post(
        "/chat",
        json={"message": "Guarda esto", "plant_id": "plant-123"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["proposed_action"] is not None
    assert data["proposed_action"]["action_type"] == "add_journal_entry"
    assert "confirm_token" in data["proposed_action"]
