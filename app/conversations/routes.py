from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from app.auth.dependency import UserIdentity, get_authenticated_user
from app.conversations.audit import log_conversation_event
from app.conversations.models import (
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationSummary,
    CreateConversationRequest,
    CreateConversationResponse,
    Message,
)
from app.conversations.store import (
    ConversationNotFoundError,
    ConversationPlantMismatchError,
    create_conversation,
    fetch_messages,
    list_conversations,
)
from app.supabase.client import build_user_client

if TYPE_CHECKING:
    from app.config.settings import Settings

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=201)
async def create_conversation_route(
    body: CreateConversationRequest,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),
) -> CreateConversationResponse:
    settings: Settings = request.app.state.settings
    start = time.monotonic()

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    conv = await create_conversation(
        client,
        user.sub,
        plant_id=body.plant_id,
        title=body.title,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    log_conversation_event(
        event_type="create",
        conversation_id=conv.conversation_id,
        user_sub=user.sub,
        status=201,
        duration_ms=elapsed_ms,
    )

    return CreateConversationResponse(conversation_id=conv.conversation_id)


@router.get("")
async def list_conversations_route(
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),
) -> ConversationListResponse:
    settings: Settings = request.app.state.settings
    start = time.monotonic()

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    convs = await list_conversations(client, settings.conversations_max_results)

    summaries = [
        ConversationSummary(
            conversation_id=c.conversation_id,
            title=c.title,
            plant_id=c.plant_id,
            updated_at=c.updated_at,
            created_at=c.created_at,
        )
        for c in convs
    ]

    elapsed_ms = int((time.monotonic() - start) * 1000)
    log_conversation_event(
        event_type="list",
        conversation_id=None,
        user_sub=user.sub,
        count=len(summaries),
        status=200,
        duration_ms=elapsed_ms,
    )

    return ConversationListResponse(conversations=summaries)


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),
) -> ConversationMessagesResponse:
    settings: Settings = request.app.state.settings
    start = time.monotonic()

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    msgs = await fetch_messages(client, conversation_id)
    if msgs is None:
        raise ConversationNotFoundError(conversation_id)

    messages = [
        Message(
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            photo_url=m.photo_url,
        )
        for m in msgs
    ]

    elapsed_ms = int((time.monotonic() - start) * 1000)
    log_conversation_event(
        event_type="get_messages",
        conversation_id=conversation_id,
        user_sub=user.sub,
        count=len(messages),
        status=200,
        duration_ms=elapsed_ms,
    )

    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=messages,
    )
