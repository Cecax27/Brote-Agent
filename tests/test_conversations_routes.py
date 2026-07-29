from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient


@pytest.fixture
def mock_supabase_client_conv():
    from unittest.mock import patch

    patcher = patch(
        "app.conversations.routes.build_user_client",
        new_callable=AsyncMock,
    )
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_create_conversation() -> AsyncMock:
    from unittest.mock import patch

    patcher = patch(
        "app.conversations.routes.create_conversation",
        new_callable=AsyncMock,
    )
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_list_conversations() -> AsyncMock:
    from unittest.mock import patch

    patcher = patch(
        "app.conversations.routes.list_conversations",
        new_callable=AsyncMock,
    )
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_fetch_messages() -> AsyncMock:
    from unittest.mock import patch

    patcher = patch(
        "app.conversations.routes.fetch_messages",
        new_callable=AsyncMock,
    )
    yield patcher.start()
    patcher.stop()


class TestCreateConversation:
    @pytest.mark.asyncio
    async def test_creates_conversation_returns_201(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_create_conversation: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        conv = MagicMock()
        conv.conversation_id = "conv-abc"
        mock_create_conversation.return_value = conv

        response = await client.post(
            "/conversations",
            json={},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["conversation_id"] == "conv-abc"
        mock_create_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_accepts_optional_plant_id_and_title(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_create_conversation: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        conv = MagicMock()
        conv.conversation_id = "conv-xyz"
        mock_create_conversation.return_value = conv

        response = await client.post(
            "/conversations",
            json={"plant_id": "plant-1", "title": "Mi charla"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        call_kwargs = mock_create_conversation.call_args.kwargs
        assert call_kwargs["plant_id"] == "plant-1"
        assert call_kwargs["title"] == "Mi charla"

    @pytest.mark.asyncio
    async def test_title_too_long_returns_422(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}

        response = await client.post(
            "/conversations",
            json={"title": "A" * 201},
            headers=auth_headers,
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        response = await client.post("/conversations", json={})
        assert response.status_code == 401


class TestListConversations:
    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_user(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_list_conversations: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_list_conversations.return_value = []

        response = await client.get("/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data == {"conversations": []}

    @pytest.mark.asyncio
    async def test_returns_conversations_list(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_list_conversations: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        from datetime import datetime, timezone

        dt_now = datetime(2025, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
        conv1 = MagicMock()
        conv1.conversation_id = "conv-1"
        conv1.title = "Hola Flora"
        conv1.plant_id = None
        conv1.updated_at = dt_now
        conv1.created_at = dt_now
        conv2 = MagicMock()
        conv2.conversation_id = "conv-2"
        conv2.title = "Mi Monstera"
        conv2.plant_id = "plant-1"
        conv2.updated_at = dt_now
        conv2.created_at = dt_now
        mock_list_conversations.return_value = [conv1, conv2]

        response = await client.get("/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["conversations"]) == 2
        assert data["conversations"][0]["conversation_id"] == "conv-1"
        assert data["conversations"][1]["conversation_id"] == "conv-2"
        assert data["conversations"][1]["plant_id"] == "plant-1"

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/conversations")
        assert response.status_code == 401


class TestGetConversationMessages:
    @pytest.mark.asyncio
    async def test_returns_messages_for_owned_conversation(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_fetch_messages: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        from datetime import datetime, timezone

        dt_now = datetime(2025, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
        msg1 = MagicMock()
        msg1.role = "user"
        msg1.content = "Hola"
        msg1.created_at = dt_now
        msg1.photo_url = None
        msg2 = MagicMock()
        msg2.role = "assistant"
        msg2.content = "¡Hola!"
        msg2.created_at = dt_now
        msg2.photo_url = None
        mock_fetch_messages.return_value = [msg1, msg2]

        response = await client.get(
            "/conversations/conv-1/messages",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-1"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][0]["photo_url"] is None

    @pytest.mark.asyncio
    async def test_foreign_conversation_returns_404(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_conv: AsyncMock,
        mock_fetch_messages: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_fetch_messages.return_value = None

        response = await client.get(
            "/conversations/foreign-id/messages",
            headers=auth_headers,
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "CONVERSATION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/conversations/conv-1/messages")
        assert response.status_code == 401
