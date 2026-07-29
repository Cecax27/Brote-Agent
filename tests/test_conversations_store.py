from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.loop import UpstreamError
from app.conversations.store import (
    append_message,
    bump_updated_at,
    create_conversation,
    fetch_history,
    fetch_messages,
    get_conversation,
    list_conversations,
    set_plant_id_once,
    set_title,
)
from app.supabase.schema import (
    COL_CONVERSATION_ID,
    COL_PLANT_ID,
    COL_ROLE,
    COL_TITLE,
    COL_UPDATED_AT,
    COL_USER_ID,
)

DEFAULT_DT = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC).isoformat()


def _conv_dict(**overrides: object) -> dict:
    base: dict[str, object] = {
        "id": "conv-1",
        "user_id": "user-abc",
        "plant_id": None,
        "title": "Conversación con Flora",
        "created_at": DEFAULT_DT,
        "updated_at": DEFAULT_DT,
    }
    for k, v in overrides.items():
        if v is not None:
            base[k] = v
        else:
            base.pop(k, None)
    return base


def _msg_dict(**overrides: object) -> dict:
    base: dict[str, object] = {
        "role": "user",
        "content": "Hola",
        "created_at": DEFAULT_DT,
        "photo_url": None,
    }
    for k, v in overrides.items():
        if v is not None:
            base[k] = v
        else:
            base.pop(k, None)
    return base


def _make_chain(execute_fn: AsyncMock) -> MagicMock:
    """Build a supabase chain mock where .execute() resolves to `execute_fn`."""
    chain = MagicMock()
    chain.execute = execute_fn
    for method in ("select", "insert", "update", "eq", "order", "limit", "maybe_single"):
        setattr(chain, method, MagicMock(return_value=chain))
    return chain


def _make_client_single(data: dict | None) -> AsyncMock:
    """For operations that use .maybe_single() — .data is a single dict or None."""
    exec_mock = AsyncMock()
    resp = MagicMock()
    resp.data = data
    exec_mock.return_value = resp
    chain = _make_chain(exec_mock)
    client = AsyncMock()
    client.table = MagicMock(return_value=chain)
    return client


def _make_client_list(data: list[dict]) -> AsyncMock:
    """For operations that return list .data."""
    exec_mock = AsyncMock()
    resp = MagicMock()
    resp.data = data
    exec_mock.return_value = resp
    chain = _make_chain(exec_mock)
    client = AsyncMock()
    client.table = MagicMock(return_value=chain)
    return client


class TestCreateConversation:
    @pytest.mark.asyncio
    async def test_inserts_user_id_from_user_sub(self) -> None:
        client = _make_client_list([_conv_dict()])

        conv = await create_conversation(client, "user-abc")
        assert conv.user_id == "user-abc"

        insert_call = client.table.return_value.insert.call_args
        assert insert_call is not None
        assert insert_call[0][0][COL_USER_ID] == "user-abc"

    @pytest.mark.asyncio
    async def test_accepts_optional_plant_id(self) -> None:
        client = _make_client_list([_conv_dict(plant_id="plant-1")])

        conv = await create_conversation(client, "user-abc", plant_id="plant-1")
        assert conv.plant_id == "plant-1"

    @pytest.mark.asyncio
    async def test_accepts_optional_title(self) -> None:
        client = _make_client_list([_conv_dict(title="Mi charla")])

        conv = await create_conversation(client, "user-abc", title="Mi charla")
        assert conv.title == "Mi charla"

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_supabase_failure(self) -> None:
        client = _make_client_list([])
        client.table.return_value.insert.return_value.execute = AsyncMock(
            side_effect=Exception("boom")
        )

        with pytest.raises(UpstreamError):
            await create_conversation(client, "user-abc")

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_empty_result(self) -> None:
        client = _make_client_list([])

        with pytest.raises(UpstreamError):
            await create_conversation(client, "user-abc")


class TestGetConversation:
    @pytest.mark.asyncio
    async def test_returns_conversation_for_owned_id(self) -> None:
        client = _make_client_single(_conv_dict())

        conv = await get_conversation(client, "conv-1")
        assert conv is not None
        assert conv.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_returns_none_for_foreign_id(self) -> None:
        client = _make_client_single(None)

        conv = await get_conversation(client, "foreign-id")
        assert conv is None

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_supabase_failure(self) -> None:
        client = _make_client_single(None)
        client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute = AsyncMock(
            side_effect=Exception("boom")
        )

        with pytest.raises(UpstreamError):
            await get_conversation(client, "conv-1")


class TestAppendMessage:
    @pytest.mark.asyncio
    async def test_inserts_message_with_no_user_id(self) -> None:
        client = _make_client_list([_msg_dict()])

        msg = await append_message(client, "conv-1", "user", "Hola")
        assert msg.role == "user"
        assert msg.content == "Hola"

        insert_call = client.table.return_value.insert.call_args
        payload = insert_call[0][0]
        assert "user_id" not in payload
        assert payload[COL_CONVERSATION_ID] == "conv-1"
        assert payload[COL_ROLE] == "user"

    @pytest.mark.asyncio
    async def test_truncates_content_over_4000(self) -> None:
        expected = "A" * 4000 + "…"
        client = _make_client_list([_msg_dict(content=expected)])

        long_content = "A" * 5000
        msg = await append_message(client, "conv-1", "assistant", long_content)
        assert len(msg.content) == 4001
        assert msg.content == expected

    @pytest.mark.asyncio
    async def test_does_not_truncate_short_content(self) -> None:
        client = _make_client_list([_msg_dict(content="Corto")])

        msg = await append_message(client, "conv-1", "user", "Corto")
        assert msg.content == "Corto"

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_supabase_failure(self) -> None:
        client = _make_client_list([])
        client.table.return_value.insert.return_value.execute = AsyncMock(
            side_effect=Exception("boom")
        )

        with pytest.raises(UpstreamError):
            await append_message(client, "conv-1", "user", "Hola")

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_empty_result(self) -> None:
        client = _make_client_list([])

        with pytest.raises(UpstreamError):
            await append_message(client, "conv-1", "user", "Hola")


class TestFetchHistory:
    @pytest.mark.asyncio
    async def test_returns_messages_oldest_first(self) -> None:
        client = _make_client_list(
            [
                _msg_dict(role="user", content="Primero"),
                _msg_dict(role="assistant", content="Segundo"),
            ]
        )

        msgs = await fetch_history(client, "conv-1", 20)
        assert len(msgs) == 2
        assert msgs[0].content == "Primero"
        assert msgs[1].content == "Segundo"

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        client = _make_client_list([_msg_dict()])

        await fetch_history(client, "conv-1", 5)
        limit_call = (
            client.table.return_value.select.return_value.eq.return_value.order.return_value.limit
        )
        limit_call.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self) -> None:
        client = _make_client_list([])

        msgs = await fetch_history(client, "conv-1", 20)
        assert msgs == []

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_supabase_failure(self) -> None:
        client = _make_client_list([])
        client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute = AsyncMock(
            side_effect=Exception("boom")
        )

        with pytest.raises(UpstreamError):
            await fetch_history(client, "conv-1", 20)


class TestBumpUpdatedAt:
    @pytest.mark.asyncio
    async def test_updates_updated_at(self) -> None:
        client = _make_client_list([])

        await bump_updated_at(client, "conv-1")
        update_call = client.table.return_value.update.call_args
        assert update_call is not None
        assert COL_UPDATED_AT in update_call[0][0]

    @pytest.mark.asyncio
    async def test_raises_upstream_error_on_failure(self) -> None:
        client = _make_client_list([])
        client.table.return_value.update.return_value.eq.return_value.execute = AsyncMock(
            side_effect=Exception("boom")
        )

        with pytest.raises(UpstreamError):
            await bump_updated_at(client, "conv-1")


class TestSetTitle:
    @pytest.mark.asyncio
    async def test_sets_title(self) -> None:
        client = _make_client_list([])

        await set_title(client, "conv-1", "Nuevo título")
        update_call = client.table.return_value.update.call_args
        assert update_call[0][0][COL_TITLE] == "Nuevo título"


class TestSetPlantIdOnce:
    @pytest.mark.asyncio
    async def test_sets_plant_id(self) -> None:
        client = _make_client_list([])

        await set_plant_id_once(client, "conv-1", "plant-1")
        update_call = client.table.return_value.update.call_args
        assert update_call[0][0][COL_PLANT_ID] == "plant-1"


class TestListConversations:
    @pytest.mark.asyncio
    async def test_returns_conversations_ordered_by_updated_at_desc(self) -> None:
        client = _make_client_list(
            [
                {
                    "id": "conv-2",
                    "title": "Chat 2",
                    "plant_id": None,
                    "updated_at": "2025-07-29T13:00:00+00:00",
                    "created_at": DEFAULT_DT,
                },
                {
                    "id": "conv-1",
                    "title": "Chat 1",
                    "plant_id": None,
                    "updated_at": "2025-07-29T12:00:00+00:00",
                    "created_at": DEFAULT_DT,
                },
            ]
        )

        convs = await list_conversations(client, 50)
        assert len(convs) == 2
        assert convs[0].conversation_id == "conv-2"
        assert convs[1].conversation_id == "conv-1"

        order_call = client.table.return_value.select.return_value.order
        order_call.assert_called_once_with(COL_UPDATED_AT, desc=True)

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        client = _make_client_list([])

        await list_conversations(client, 10)
        limit_call = client.table.return_value.select.return_value.order.return_value.limit
        limit_call.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_conversations(self) -> None:
        client = _make_client_list([])

        convs = await list_conversations(client, 50)
        assert convs == []


class TestFetchMessages:
    @pytest.mark.asyncio
    async def test_returns_messages_for_owned_conversation(self) -> None:
        client = _make_client_list(
            [
                _msg_dict(role="user", content="A"),
                _msg_dict(role="assistant", content="B"),
            ]
        )

        with patch(
            "app.conversations.store.get_conversation",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = MagicMock()
            msgs = await fetch_messages(client, "conv-1")
            assert msgs is not None
            assert len(msgs) == 2
            assert msgs[0].content == "A"
            assert msgs[1].content == "B"

    @pytest.mark.asyncio
    async def test_returns_none_for_foreign_id(self) -> None:
        client = _make_client_single(None)

        msgs = await fetch_messages(client, "foreign-id")
        assert msgs is None
