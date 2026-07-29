from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

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
                import json

                event_data["data"] = json.loads(line[6:])
        if event_data["event"]:
            events.append(event_data)
    return events


@pytest.fixture
def mock_gemini_sse():
    patcher = patch("app.api.sse_routes.call_gemini", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_auth_sse():
    patcher = patch("app.auth.dependency.verify_access_token", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_context_sse():
    patcher = patch("app.api.sse_routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client_sse():
    patcher = patch("app.api.sse_routes.build_user_client", new_callable=AsyncMock)
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

    from datetime import UTC, datetime

    dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
    conv = MagicMock()
    conv.conversation_id = "conv-test-123"
    conv.user_id = "test-user-id"
    conv.plant_id = None
    conv.title = "Conversación con Flora"
    conv.created_at = dt
    conv.updated_at = dt

    mocks["create_conversation"].return_value = conv
    mocks["get_conversation"].return_value = conv
    mocks["fetch_history"].return_value = []

    yield mocks

    for patcher in patchers.values():
        patcher.stop()


class TestChatStreamHappyPath:
    @pytest.mark.asyncio
    async def test_streams_status_events_for_new_conversation(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini_sse.return_value = {"reply": "Hola"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola Flora"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = _parse_sse(response.text)

        step_names = [e["data"].get("step") for e in events if e["event"] == "status"]
        assert "writing_memory" in step_names
        assert "thinking" in step_names
        assert "result" in [e["event"] for e in events]
        assert "loading_memory" not in step_names

    @pytest.mark.asyncio
    async def test_result_event_contains_chat_response(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini_sse.return_value = {"reply": "Hola, ¿cómo estás?"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola Flora"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["reply"] == "Hola, ¿cómo estás?"
        assert result["data"]["conversation_id"] == "conv-test-123"

    @pytest.mark.asyncio
    async def test_status_events_have_correct_shape(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini_sse.return_value = {"reply": "Hola"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        status_events = [e for e in events if e["event"] == "status"]
        for se in status_events:
            assert "step" in se["data"]
            assert "message" in se["data"]
            assert isinstance(se["data"]["step"], str)
            assert isinstance(se["data"]["message"], str)

    @pytest.mark.asyncio
    async def test_plant_context_emits_reading_garden(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini_sse.return_value = {"reply": "Tu planta está bien"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        conv = mock_conv_store_sse["create_conversation"].return_value
        conv.plant_id = "plant-456"

        response = await client.post(
            "/chat/stream",
            json={"message": "¿Cómo está mi planta?", "plant_id": "plant-456"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        reading = [e for e in events if e["data"].get("step") == "reading_garden"]
        assert len(reading) > 0


class TestChatStreamExistingConversation:
    @pytest.mark.asyncio
    async def test_emits_loading_memory_for_existing(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini_sse.return_value = {"reply": "Continuamos"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        from datetime import UTC, datetime

        from app.conversations.models import Message as MessageModel

        mock_conv_store_sse["fetch_history"].return_value = [
            MessageModel(
                role="user",
                content="Mensaje anterior",
                created_at=datetime(2025, 7, 29, 11, 0, 0, tzinfo=UTC),
                photo_url=None,
            ),
            MessageModel(
                role="assistant",
                content="Respuesta anterior",
                created_at=datetime(2025, 7, 29, 11, 0, 1, tzinfo=UTC),
                photo_url=None,
            ),
        ]

        response = await client.post(
            "/chat/stream",
            json={
                "message": "Continuemos",
                "conversation_id": "11111111-1111-1111-1111-111111111111",
            },
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        memory = [e for e in events if e["data"].get("step") == "loading_memory"]
        assert len(memory) > 0

    @pytest.mark.asyncio
    async def test_foreign_conversation_returns_404_error(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_conv_store_sse["get_conversation"].return_value = None

        response = await client.post(
            "/chat/stream",
            json={
                "message": "Hola",
                "conversation_id": "11111111-1111-1111-1111-111111111111",
            },
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "CONVERSATION_NOT_FOUND"
        mock_gemini_sse.assert_not_called()

    @pytest.mark.asyncio
    async def test_plant_mismatch_returns_400_error(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_sse.return_value = {"id": "test-user-id"}
        conv = mock_conv_store_sse["get_conversation"].return_value
        conv.plant_id = "plant-A"

        response = await client.post(
            "/chat/stream",
            json={
                "message": "Hola",
                "conversation_id": "11111111-1111-1111-1111-111111111111",
                "plant_id": "plant-B",
            },
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "CONVERSATION_PLANT_MISMATCH"


class TestChatStreamKillSwitch:
    @pytest.mark.asyncio
    async def test_disabled_returns_single_shot_json(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
        settings,
    ) -> None:
        settings.dynamic_states_enabled = False
        mock_gemini_sse.return_value = {"reply": "Hola"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola Flora"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Hola"
        assert data["conversation_id"] == "conv-test-123"


class TestChatStream502:
    @pytest.mark.asyncio
    async def test_gemini_failure_emits_error_event(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
    ) -> None:
        from app.agent.loop import UpstreamError

        mock_gemini_sse.side_effect = UpstreamError("fallo")
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "UPSTREAM_ERROR"
        assert "result" not in [e["event"] for e in events]


class TestChatStreamHumorToggle:
    @pytest.mark.asyncio
    async def test_humor_disabled_excludes_humorous_variants(
        self,
        client: AsyncClient,
        mock_gemini_sse: AsyncMock,
        mock_auth_sse: AsyncMock,
        mock_supabase_client_sse: AsyncMock,
        mock_supabase_context_sse: AsyncMock,
        mock_conv_store_sse: dict,
        auth_headers: dict,
        settings,
    ) -> None:
        settings.dynamic_states_include_humor = False
        mock_gemini_sse.return_value = {"reply": "Hola"}
        mock_auth_sse.return_value = {"id": "test-user-id"}
        mock_supabase_context_sse.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat/stream",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        events = _parse_sse(response.text)
        status_messages = [e["data"]["message"] for e in events if e["event"] == "status"]
        humorous = [
            "sabiduría vegetal",
            "hojas me están contando",
            "lupa virtual",
            "consultar con las hojas",
        ]
        for msg in status_messages:
            for phrase in humorous:
                assert phrase not in msg
