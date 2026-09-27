"""Tests for the inline auto-vision flow inside /chat and /chat/stream.

When Flora decides a photo would help, the chat endpoint:
  1. emits an `analyzing_photo` status event,
  2. resolves + downloads + analyzes the referenced photo server-side,
  3. runs a second Gemini call whose `reply` is the user-facing answer.

The original `vision_request` is NOT surfaced to the client.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient  # noqa: TC002

from app.agent.auto_vision import (
    VisionSubCallMissingPhotoError,
    VisionSubCallUpstreamError,
)
from app.supabase.context import ContextBundle


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_data: dict = {"event": "", "data": {}}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_data["event"] = line[7:]
            elif line.startswith("data: "):
                event_data["data"] = json.loads(line[6:])
        if event_data["event"]:
            events.append(event_data)
    return events


@pytest.fixture
def mock_first_gemini_sse():
    """Patches call_gemini used by the SSE route (the first-pass call)."""
    patcher = patch("app.api.sse_routes.call_gemini", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_auto_vision_run_sse():
    """Patches run_auto_vision_followup used by the SSE route."""
    patcher = patch("app.api.sse_routes.run_auto_vision_followup", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_auto_vision_text_sse():
    """Patches run_text_only_followup used by the SSE route."""
    patcher = patch("app.api.sse_routes.run_text_only_followup", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_auth_sse():
    patcher = patch("app.auth.dependency.verify_access_token", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client_sse():
    patcher = patch("app.api.sse_routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_context_sse():
    patcher = patch("app.api.sse_routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_conv_store_sse() -> dict[str, AsyncMock]:
    patchers: dict[str, MagicMock] = {}
    mocks: dict[str, AsyncMock] = {}
    targets = [
        "create_conversation",
        "get_conversation",
        "append_message",
        "fetch_history",
        "bump_updated_at",
        "set_title",
        "set_plant_id_once",
    ]
    for name in targets:
        patcher = patch(f"app.api.sse_routes.{name}", new_callable=AsyncMock)
        mocks[name] = patcher.start()
        patchers[name] = patcher

    dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
    conv = MagicMock()
    conv.conversation_id = "conv-test-123"
    conv.user_id = "test-user-id"
    conv.plant_id = "plant-abc"
    conv.title = "Conversación con Flora"
    conv.created_at = dt
    conv.updated_at = dt

    mocks["create_conversation"].return_value = conv
    mocks["get_conversation"].return_value = conv
    mocks["fetch_history"].return_value = []

    yield mocks

    for patcher in patchers.values():
        patcher.stop()


# ---------------------------------------------------------------------------
# Streaming (`/chat/stream`) — auto-vision happy path
# ---------------------------------------------------------------------------


class TestChatStreamAutoVisionHappyPath:
    @pytest.mark.asyncio
    async def test_emits_analyzing_photo_status_when_vision_request_present(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        # First Gemini call returns a vision_request → triggers auto-vision.
        mock_first_gemini_sse.return_value = {
            "reply": "déjame mirar la foto",
            "vision_request": {
                "reason_es": "Las manchas necesitan verse para diagnosticar.",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        # Second-pass call returns a text-only reply informed by the photo.
        mock_auto_vision_run_sse.return_value = {
            "reply": "Veo manchas por exceso de riego; baja la frecuencia.",
        }

        response = await client.post(
            "/chat/stream",
            json={"message": "¿Qué tiene mi Monstera?"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        status_steps = [e["data"]["step"] for e in events if e["event"] == "status"]
        assert "analyzing_photo" in status_steps

    @pytest.mark.asyncio
    async def test_user_facing_reply_comes_from_second_pass(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first pass reply — should not surface",
            "vision_request": {
                "reason_es": "Quiero ver la hoja.",
                "suggested_ref": {
                    "kind": "journal_entry",
                    "journal_entry_id": "11111111-2222-3333-4444-555555555555",
                },
            },
        }
        mock_auto_vision_run_sse.return_value = {
            "reply": "Final reply informed by the photo.",
        }

        response = await client.post(
            "/chat/stream",
            json={"message": "¿Qué le pasa?"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["reply"] == "Final reply informed by the photo."
        # The first-pass reply must never reach the client.
        assert "first pass reply" not in result["data"]["reply"]

    @pytest.mark.asyncio
    async def test_response_does_not_include_vision_request_field(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first",
            "vision_request": {
                "reason_es": "porque sí",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        mock_auto_vision_run_sse.return_value = {"reply": "final"}

        response = await client.post(
            "/chat/stream",
            json={"message": "x"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        result = next(e for e in events if e["event"] == "result")
        assert "vision_request" not in result["data"]

    @pytest.mark.asyncio
    async def test_no_vision_request_skips_analyzing_photo(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {"reply": "Direct reply."}

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        status_steps = [e["data"]["step"] for e in events if e["event"] == "status"]
        assert "analyzing_photo" not in status_steps
        # run_auto_vision_followup must NOT be called when there's no vision request.
        mock_auto_vision_run_sse.assert_not_called()
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["reply"] == "Direct reply."

    @pytest.mark.asyncio
    async def test_persists_second_pass_reply_as_assistant_turn(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first",
            "vision_request": {
                "reason_es": "x",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        mock_auto_vision_run_sse.return_value = {"reply": "second-pass reply"}

        response = await client.post(
            "/chat/stream",
            json={"message": "x"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        append_calls = mock_conv_store_sse["append_message"].call_args_list
        assert len(append_calls) == 2
        # The assistant turn stores the second-pass reply, not the first.
        assert append_calls[1][0][2] == "assistant"
        assert append_calls[1][0][3] == "second-pass reply"


# ---------------------------------------------------------------------------
# Streaming — auto-vision failure modes
# ---------------------------------------------------------------------------


class TestChatStreamAutoVisionFailures:
    @pytest.mark.asyncio
    async def test_missing_photo_falls_back_to_text_only_followup(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auto_vision_text_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first",
            "vision_request": {
                "reason_es": "x",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        mock_auto_vision_run_sse.side_effect = VisionSubCallMissingPhotoError(
            "Imagen no encontrada."
        )
        mock_auto_vision_text_sse.return_value = {
            "reply": "No tengo foto, pero por lo que cuentas…",
        }

        response = await client.post(
            "/chat/stream",
            json={"message": "x"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["reply"] == "No tengo foto, pero por lo que cuentas…"
        mock_auto_vision_text_sse.assert_called_once()

    @pytest.mark.asyncio
    async def test_vision_gemini_upstream_failure_emits_error(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first",
            "vision_request": {
                "reason_es": "x",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        mock_auto_vision_run_sse.side_effect = VisionSubCallUpstreamError(
            "El servicio de visión no respondió."
        )

        response = await client.post(
            "/chat/stream",
            json={"message": "x"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "UPSTREAM_ERROR"
        assert "visión" in error_events[0]["data"]["error"]["message"]

    @pytest.mark.asyncio
    async def test_text_only_followup_failure_emits_error(
        self,
        client: AsyncClient,
        mock_first_gemini_sse: AsyncMock,
        mock_auto_vision_run_sse: AsyncMock,
        mock_auto_vision_text_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])
        mock_first_gemini_sse.return_value = {
            "reply": "first",
            "vision_request": {
                "reason_es": "x",
                "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
            },
        }
        mock_auto_vision_run_sse.side_effect = VisionSubCallMissingPhotoError(
            "Imagen no encontrada."
        )
        mock_auto_vision_text_sse.side_effect = VisionSubCallUpstreamError(
            "El servicio de IA no respondió."
        )

        response = await client.post(
            "/chat/stream",
            json={"message": "x"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "UPSTREAM_ERROR"


# ---------------------------------------------------------------------------
# Single-shot `/chat` — auto-vision happy path
# ---------------------------------------------------------------------------


class TestChatSingleShotAutoVision:
    @pytest.mark.asyncio
    async def test_single_shot_surfaces_second_pass_reply(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
        settings,
    ) -> None:
        settings.dynamic_states_enabled = False
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])
        conv = mock_conversation_store["create_conversation"].return_value
        conv.plant_id = "plant-abc"

        # First call → vision_request; second call (auto-vision followup) → text reply.
        mock_gemini.side_effect = [
            {
                "reply": "first-pass",
                "vision_request": {
                    "reason_es": "x",
                    "suggested_ref": {"kind": "plant_latest", "plant_id": "plant-abc"},
                },
            },
            {"reply": "single-shot final reply"},
        ]

        with patch(
            "app.api.routes.run_auto_vision_followup",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = {"reply": "single-shot final reply"}

            response = await client.post(
                "/chat",
                json={"message": "x"},
                headers=auth_headers,
            )

            assert mock_run.called
            data = response.json()
            assert data["reply"] == "single-shot final reply"
            assert "vision_request" not in data

    @pytest.mark.asyncio
    async def test_single_shot_no_vision_request_unchanged(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
        settings,
    ) -> None:
        settings.dynamic_states_enabled = False
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])
        mock_gemini.return_value = {"reply": "Direct reply, no vision needed."}

        with patch("app.api.routes.run_auto_vision_followup", new_callable=AsyncMock) as mock_run:
            response = await client.post(
                "/chat",
                json={"message": "x"},
                headers=auth_headers,
            )

            mock_run.assert_not_called()
            data = response.json()
            assert data["reply"] == "Direct reply, no vision needed."
            assert "vision_request" not in data

    @pytest.mark.asyncio
    async def test_single_shot_response_omits_vision_request_field(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
        settings,
    ) -> None:
        settings.dynamic_states_enabled = False
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])
        mock_gemini.return_value = {"reply": "hi"}

        response = await client.post("/chat", json={"message": "x"}, headers=auth_headers)

        data = response.json()
        assert "vision_request" not in data
        assert set(data.keys()) >= {"conversation_id", "reply", "proposed_action"}
