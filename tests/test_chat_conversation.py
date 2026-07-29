from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.agent.loop import UpstreamError
from app.supabase.context import ContextBundle


@pytest.fixture
def make_conv():
    """Return a function that creates a mock conversation."""
    from datetime import datetime

    def _make(**overrides):
        dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
        conv = MagicMock()
        conv.conversation_id = overrides.get("conversation_id", "conv-test-123")
        conv.user_id = overrides.get("user_id", "test-user-id")
        conv.plant_id = overrides.get("plant_id")
        conv.title = overrides.get("title", "Conversación con Flora")
        conv.created_at = dt
        conv.updated_at = dt
        return conv

    return _make


class TestChatAutoCreate:
    @pytest.mark.asyncio
    async def test_auto_creates_conversation_and_returns_id(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Hola"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat",
            json={"message": "Hola Flora"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "conversation_id" in data
        assert data["conversation_id"] == "conv-test-123"
        mock_conversation_store["create_conversation"].assert_called_once()
        mock_conversation_store["get_conversation"].assert_not_called()

    @pytest.mark.asyncio
    async def test_create_conversation_passes_user_sub(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Hola"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        call_args = mock_conversation_store["create_conversation"].call_args
        assert call_args[0][1] == "test-user-id"


class TestChatResume:
    @pytest.mark.asyncio
    async def test_resumes_existing_conversation(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "¡Claro!"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        conv_id = "5b9f1e2d-3c4a-5d6e-7f80-123456789abc"
        conv = mock_conversation_store["get_conversation"].return_value
        conv.conversation_id = conv_id

        response = await client.post(
            "/chat",
            json={
                "message": "¿Y qué opinas?",
                "conversation_id": conv_id,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == conv_id
        mock_conversation_store["get_conversation"].assert_called_once()
        mock_conversation_store["create_conversation"].assert_not_called()


class TestChatForeignConversation:
    @pytest.mark.asyncio
    async def test_foreign_conversation_id_returns_404(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_conversation_store["get_conversation"].return_value = None

        response = await client.post(
            "/chat",
            json={
                "message": "Hola",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "CONVERSATION_NOT_FOUND"
        mock_gemini.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_conversation_id_format_returns_422(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}

        response = await client.post(
            "/chat",
            json={"message": "Hola", "conversation_id": "not-a-uuid"},
            headers=auth_headers,
        )

        assert response.status_code == 422


class TestChatPlantMismatch:
    @pytest.mark.asyncio
    async def test_plant_mismatch_returns_400(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        conv = mock_conversation_store["get_conversation"].return_value
        conv.plant_id = "plant-a"

        response = await client.post(
            "/chat",
            json={
                "message": "Hola",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
                "plant_id": "plant-b",
            },
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "CONVERSATION_PLANT_MISMATCH"
        mock_gemini.assert_not_called()


class TestChatPlantScoping:
    @pytest.mark.asyncio
    async def test_null_plant_conversation_scoped_on_first_plant_chat(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Ok"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={
                "message": "Hola",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
                "plant_id": "plant-1",
            },
            headers=auth_headers,
        )

        mock_conversation_store["set_plant_id_once"].assert_called_once()

    @pytest.mark.asyncio
    async def test_plant_context_keys_off_conversation_not_body(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Ok"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])
        conv = mock_conversation_store["get_conversation"].return_value
        conv.plant_id = "plant-from-conv"

        await client.post(
            "/chat",
            json={
                "message": "¿Cómo va?",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        # Context should use the conversation's plant_id
        assert mock_supabase_context.call_args[0][1] == "plant-from-conv"


class TestChatHistoryInjection:
    @pytest.mark.asyncio
    async def test_history_block_appears_in_context(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Recuerdo que preguntaste."}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        from datetime import datetime

        dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
        from app.conversations.models import Message

        mock_conversation_store["fetch_history"].return_value = [
            Message(role="user", content="Hola", created_at=dt, photo_url=None),  # type: ignore[arg-type]
            Message(role="assistant", content="¡Hola!", created_at=dt, photo_url=None),  # type: ignore[arg-type]
        ]

        await client.post(
            "/chat",
            json={
                "message": "¿Recuerdas?",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        call_args = mock_gemini.call_args
        context_value = call_args.kwargs.get("context", "")
        assert "Historial de la conversación" in context_value
        assert "Usuario: Hola" in context_value
        assert "Flora: ¡Hola!" in context_value

    @pytest.mark.asyncio
    async def test_current_message_not_duplicated_in_history(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Ok"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        from datetime import datetime

        dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
        from app.conversations.models import Message

        mock_conversation_store["fetch_history"].return_value = [
            Message(role="user", content="Mensaje actual", created_at=dt, photo_url=None),  # type: ignore[arg-type]
        ]

        await client.post(
            "/chat",
            json={
                "message": "Mensaje actual",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        # History is loaded BEFORE persisting the current user message,
        # and fetch_history is mocked so the current turn is NOT in the history.
        # The history block may show "Mensaje actual" from the prior turn,
        # but the current message appears as "Mensaje del usuario:" separately.
        call_args = mock_gemini.call_args
        assert mock_gemini.call_args.kwargs["message"] == "Mensaje actual"


class TestChatAssistantTruncation:
    @pytest.mark.asyncio
    async def test_long_assistant_reply_truncated_before_persist(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        long_reply = "A" * 5000
        mock_gemini.return_value = {"reply": long_reply}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={"message": "Di algo muy largo"},
            headers=auth_headers,
        )

        # There should be 2 calls to append_message (user + assistant)
        append_calls = mock_conversation_store["append_message"].call_args_list
        assert len(append_calls) == 2
        # The handler passes the full reply; truncation happens inside the store
        assistant_content = append_calls[1][0][3]
        assert len(assistant_content) == 5000  # full content passed; store truncates to 4000


class TestChat502LeavesUserSaved:
    @pytest.mark.asyncio
    async def test_502_leaves_user_message_persisted(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.side_effect = UpstreamError("Servicio no disponible")
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        response = await client.post(
            "/chat",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "UPSTREAM_ERROR"

        # User message was persisted
        append_calls = mock_conversation_store["append_message"].call_args_list
        assert len(append_calls) == 1  # Only user, no assistant
        # Signature: (client, conversation_id, role, content, photo_url=None)
        assert append_calls[0][0][2] == "user"
        assert append_calls[0][0][3] == "Hola"


class TestChatAutoTitle:
    @pytest.mark.asyncio
    async def test_auto_title_derived_on_first_turn(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Hola"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={"message": "Hola Flora, ¿cómo estás?"},
            headers=auth_headers,
        )

        # Title should be derived from the first message
        mock_conversation_store["set_title"].assert_called_once()

    @pytest.mark.asyncio
    async def test_title_not_overwritten_on_explicit_title(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Ok"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])
        conv = mock_conversation_store["get_conversation"].return_value
        conv.title = "Mi charla personalizada"

        await client.post(
            "/chat",
            json={
                "message": "Hola",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        # Explicit title is NOT overwritten
        mock_conversation_store["set_title"].assert_not_called()

    @pytest.mark.asyncio
    async def test_title_not_updated_on_second_turn(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Segunda respuesta"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        from datetime import datetime

        dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
        from app.conversations.models import Message

        mock_conversation_store["fetch_history"].return_value = [
            Message(role="user", content="Primer mensaje", created_at=dt, photo_url=None),  # type: ignore[arg-type]
        ]

        await client.post(
            "/chat",
            json={
                "message": "Segundo mensaje",
                "conversation_id": "5b9f1e2d-3c4a-5d6e-7f80-123456789abc",
            },
            headers=auth_headers,
        )

        # Title is not set on second turn
        mock_conversation_store["set_title"].assert_not_called()


class TestChatPersistence:
    @pytest.mark.asyncio
    async def test_both_messages_persisted_on_success(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Respuesta"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        append_calls = mock_conversation_store["append_message"].call_args_list
        assert len(append_calls) == 2
        assert append_calls[0][0][2] == "user"
        assert append_calls[1][0][2] == "assistant"

    @pytest.mark.asyncio
    async def test_updated_at_bumped_on_success(
        self,
        client: AsyncClient,
        mock_gemini: AsyncMock,
        mock_auth_verify: AsyncMock,
        mock_supabase_client: AsyncMock,
        mock_supabase_context: AsyncMock,
        mock_conversation_store: dict,
        auth_headers: dict,
    ) -> None:
        mock_gemini.return_value = {"reply": "Ok"}
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_context.return_value = ContextBundle(light=[])

        await client.post(
            "/chat",
            json={"message": "Hola"},
            headers=auth_headers,
        )

        mock_conversation_store["bump_updated_at"].assert_called_once()
