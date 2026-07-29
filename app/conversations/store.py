from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.agent.loop import UpstreamError
from app.conversations.models import Conversation, ConversationSummary, Message
from app.supabase.schema import (
    COL_CONTENT,
    COL_CONVERSATION_ID,
    COL_CREATED_AT,
    COL_PHOTO_URL,
    COL_PLANT_ID,
    COL_ROLE,
    COL_TITLE,
    COL_UPDATED_AT,
    COL_USER_ID,
    TABLE_AI_CONVERSATIONS,
    TABLE_AI_MESSAGES,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

_STORE_UPSTREAM_MSG = "El servicio de datos no respondió. Inténtalo de nuevo en un momento."


class ConversationNotFoundError(Exception):
    """The conversation does not exist or does not belong to the caller."""

    def __init__(self, conversation_id: str | None = None) -> None:
        super().__init__(conversation_id)
        self.conversation_id = conversation_id


class ConversationPlantMismatchError(Exception):
    """The conversation's plant_id conflicts with the request's plant_id."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


def _parse_conversation(row: dict) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row[COL_USER_ID],
        plant_id=row.get(COL_PLANT_ID),
        title=row.get(COL_TITLE, "Conversación con Flora"),
        created_at=_parse_dt(row[COL_CREATED_AT]),
        updated_at=_parse_dt(row[COL_UPDATED_AT]),
    )


def _parse_conversation_summary(row: dict) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=row["id"],
        title=row.get(COL_TITLE, "Conversación con Flora"),
        plant_id=row.get(COL_PLANT_ID),
        created_at=_parse_dt(row[COL_CREATED_AT]),
        updated_at=_parse_dt(row[COL_UPDATED_AT]),
    )


def _parse_message(row: dict) -> Message:
    return Message(
        role=row[COL_ROLE],
        content=row[COL_CONTENT],
        created_at=_parse_dt(row[COL_CREATED_AT]),
        photo_url=row.get(COL_PHOTO_URL),
    )


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


async def create_conversation(
    client: AsyncClient,
    user_sub: str,
    plant_id: str | None = None,
    title: str | None = None,
) -> Conversation:
    """Create a new conversation. user_id is supplied as user.sub — never from the body."""
    row: dict[str, str | None] = {COL_USER_ID: user_sub}
    if plant_id is not None:
        row[COL_PLANT_ID] = plant_id
    if title is not None:
        row[COL_TITLE] = title

    try:
        result = await client.table(TABLE_AI_CONVERSATIONS).insert(row).execute()
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    data = result.data
    if not data:
        raise UpstreamError(_STORE_UPSTREAM_MSG)
    return _parse_conversation(data[0])


async def get_conversation(
    client: AsyncClient,
    conversation_id: str,
) -> Conversation | None:
    """Return the conversation if the caller owns it (RLS-scoped). None otherwise."""
    try:
        result = (
            await client.table(TABLE_AI_CONVERSATIONS)
            .select("*")
            .eq("id", conversation_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    if not result.data:
        return None
    return _parse_conversation(result.data)


async def append_message(
    client: AsyncClient,
    conversation_id: str,
    role: str,
    content: str,
    photo_url: str | None = None,
) -> Message:
    """Insert a message row. Truncate content > 4000 with trailing '…' before insert."""
    truncated = _truncate_content(content)

    row: dict[str, str | None] = {
        COL_CONVERSATION_ID: conversation_id,
        COL_ROLE: role,
        COL_CONTENT: truncated,
    }
    if photo_url is not None:
        row[COL_PHOTO_URL] = photo_url

    try:
        result = await client.table(TABLE_AI_MESSAGES).insert(row).execute()
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    data = result.data
    if not data:
        raise UpstreamError(_STORE_UPSTREAM_MSG)
    return _parse_message(data[0])


async def fetch_history(
    client: AsyncClient,
    conversation_id: str,
    limit: int,
) -> list[Message]:
    """Fetch recent messages oldest→newest. RLS-scoped."""
    try:
        result = (
            await client.table(TABLE_AI_MESSAGES)
            .select(f"{COL_ROLE}, {COL_CONTENT}, {COL_CREATED_AT}, {COL_PHOTO_URL}")
            .eq(COL_CONVERSATION_ID, conversation_id)
            .order(COL_CREATED_AT, desc=False)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    return [_parse_message(row) for row in (result.data or [])]


async def bump_updated_at(client: AsyncClient, conversation_id: str) -> None:
    """Update ai_conversations.updated_at = now(). RLS-scoped."""
    try:
        await (
            client.table(TABLE_AI_CONVERSATIONS)
            .update({COL_UPDATED_AT: datetime.now(UTC).isoformat()})
            .eq("id", conversation_id)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc


async def set_title(client: AsyncClient, conversation_id: str, title: str) -> None:
    """Set the conversation title. RLS-scoped."""
    try:
        await (
            client.table(TABLE_AI_CONVERSATIONS)
            .update({COL_TITLE: title})
            .eq("id", conversation_id)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc


async def set_plant_id_once(
    client: AsyncClient,
    conversation_id: str,
    plant_id: str,
) -> None:
    """Scope a null-plant conversation to a plant_id. RLS-scoped."""
    try:
        await (
            client.table(TABLE_AI_CONVERSATIONS)
            .update({COL_PLANT_ID: plant_id})
            .eq("id", conversation_id)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc


async def list_conversations(
    client: AsyncClient,
    limit: int,
) -> list[ConversationSummary]:
    """List the caller's conversations ordered by updated_at desc. RLS-scoped."""
    try:
        result = (
            await client.table(TABLE_AI_CONVERSATIONS)
            .select("id, title, plant_id, updated_at, created_at")
            .order(COL_UPDATED_AT, desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    return [_parse_conversation_summary(row) for row in (result.data or [])]


async def fetch_messages(
    client: AsyncClient,
    conversation_id: str,
) -> list[Message] | None:
    """Return messages for a conversation if owned; None otherwise. Oldest→newest."""
    conv = await get_conversation(client, conversation_id)
    if conv is None:
        return None

    try:
        result = (
            await client.table(TABLE_AI_MESSAGES)
            .select(f"{COL_ROLE}, {COL_CONTENT}, {COL_CREATED_AT}, {COL_PHOTO_URL}")
            .eq(COL_CONVERSATION_ID, conversation_id)
            .order(COL_CREATED_AT, desc=False)
            .execute()
        )
    except Exception as exc:
        raise UpstreamError(_STORE_UPSTREAM_MSG) from exc

    return [_parse_message(row) for row in (result.data or [])]


def _truncate_content(content: str) -> str:
    if len(content) <= 4000:
        return content
    return content[:4000] + "…"
