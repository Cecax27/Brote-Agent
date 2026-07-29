import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.actions.helpers import build_proposed_action
from app.agent.loop import UpstreamError, call_gemini
from app.api.routes import (
    ACTION_RESPONSE_SCHEMA,
    ChatRequest,
    ChatResponse,
    _build_vision_request,
)
from app.auth.dependency import UserIdentity, get_authenticated_user
from app.conversations.history import format_history_block, trim_to_budget
from app.conversations.store import (
    ConversationNotFoundError,
    ConversationPlantMismatchError,
    append_message,
    bump_updated_at,
    create_conversation,
    fetch_history,
    get_conversation,
    set_plant_id_once,
    set_title,
)
from app.conversations.titles import derive_title
from app.dynamic_states.emitter import error_event, result_event, status_event
from app.dynamic_states.statuses import pick_status
from app.logging import get_logger
from app.supabase.client import build_user_client
from app.supabase.context import build_plant_context, format_context_for_gemini

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter()

_UPSTREAM_MSG = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."
_DEFAULT_TITLE = "Conversación con Flora"


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),
):
    settings: "Settings" = request.app.state.settings

    if not settings.dynamic_states_enabled:
        return await _single_shot_chat(body, request, user, settings)

    return StreamingResponse(
        _stream_chat_events(body, request, user, settings),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _stream_chat_events(
    body: ChatRequest,
    request: Request,
    user: UserIdentity,
    settings: "Settings",
) -> AsyncGenerator[str, None]:
    start = time.monotonic()
    include_humor = settings.dynamic_states_include_humor

    client = await build_user_client(
        settings.supabase_url, settings.supabase_anon_key, user.access_token
    )

    is_new = body.conversation_id is None
    if is_new:
        conversation = await create_conversation(
            client, user.sub, plant_id=body.plant_id, title=None
        )
    else:
        yield status_event(
            "loading_memory",
            pick_status("loading_memory", include_humor=include_humor),
        )
        conversation = await get_conversation(client, str(body.conversation_id))
        if conversation is None:
            yield error_event(
                "CONVERSATION_NOT_FOUND",
                f"Conversación {body.conversation_id} no encontrada.",
            )
            return

    conv_id = conversation.conversation_id

    if (
        conversation.plant_id is not None
        and body.plant_id is not None
        and conversation.plant_id != body.plant_id
    ):
        yield error_event(
            "CONVERSATION_PLANT_MISMATCH",
            "Esta conversación pertenece a otra planta.",
        )
        return

    if conversation.plant_id is None and body.plant_id is not None:
        await set_plant_id_once(client, conv_id, body.plant_id)
        conversation.plant_id = body.plant_id

    history_messages = await fetch_history(client, conv_id, settings.history_max_messages)
    was_empty = len(history_messages) == 0
    if not was_empty:
        yield status_event(
            "loading_memory",
            pick_status("loading_memory", include_humor=include_humor),
        )

    history_messages = trim_to_budget(
        history_messages, settings.history_max_messages, settings.history_max_chars
    )
    history_block = format_history_block(history_messages)

    yield status_event(
        "writing_memory",
        pick_status("writing_memory", include_humor=include_humor),
    )
    await append_message(client, conv_id, "user", body.message)

    effective_plant_id = conversation.plant_id
    if effective_plant_id:
        yield status_event(
            "reading_garden",
            pick_status("reading_garden", include_humor=include_humor),
        )

    bundle = await build_plant_context(
        client,
        effective_plant_id,
        max_plants=settings.context_max_plants,
        max_entries=settings.context_max_recent_entries,
    )
    context_str = format_context_for_gemini(bundle, user_name=user.display_name)
    if history_block:
        context_str = f"{history_block}\n\n{context_str}"

    yield status_event(
        "thinking",
        pick_status("thinking", include_humor=include_humor),
    )

    try:
        result = await call_gemini(
            message=body.message,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_output_tokens,
            context=context_str,
            response_schema=ACTION_RESPONSE_SCHEMA,
        )
    except UpstreamError:
        _log_failed(start, user.sub, conv_id)
        yield error_event("UPSTREAM_ERROR", _UPSTREAM_MSG)
        return

    if not isinstance(result, dict):
        yield error_event("UPSTREAM_ERROR", _UPSTREAM_MSG)
        return

    reply = str(result.get("reply", ""))
    proposed_action = build_proposed_action(result, effective_plant_id, user.sub, settings)
    vision_request = _build_vision_request(result, effective_plant_id)

    yield status_event(
        "writing_memory",
        pick_status("writing_memory", include_humor=include_humor),
    )
    await append_message(client, conv_id, "assistant", reply)

    if was_empty and is_new and conversation.title == _DEFAULT_TITLE:
        derived = derive_title(body.message, settings.conversation_title_max_chars)
        if derived is not None:
            await set_title(client, conv_id, derived)

    await bump_updated_at(client, conv_id)

    _log_complete(start, user.sub, conv_id)

    yield result_event(_build_response(conv_id, reply, proposed_action, vision_request))


async def _single_shot_chat(
    body: ChatRequest,
    request: Request,
    user: UserIdentity,
    settings: "Settings",
) -> ChatResponse:
    """Single-shot JSON response when dynamic states are disabled."""
    start = time.monotonic()

    client = await build_user_client(
        settings.supabase_url, settings.supabase_anon_key, user.access_token
    )

    is_new = body.conversation_id is None
    if is_new:
        conversation = await create_conversation(
            client, user.sub, plant_id=body.plant_id, title=None
        )
    else:
        conversation = await get_conversation(client, str(body.conversation_id))
        if conversation is None:
            raise ConversationNotFoundError(str(body.conversation_id))

    conv_id = conversation.conversation_id

    if (
        conversation.plant_id is not None
        and body.plant_id is not None
        and conversation.plant_id != body.plant_id
    ):
        raise ConversationPlantMismatchError

    if conversation.plant_id is None and body.plant_id is not None:
        await set_plant_id_once(client, conv_id, body.plant_id)
        conversation.plant_id = body.plant_id

    history_messages = await fetch_history(client, conv_id, settings.history_max_messages)
    was_empty = len(history_messages) == 0
    history_messages = trim_to_budget(
        history_messages, settings.history_max_messages, settings.history_max_chars
    )
    history_block = format_history_block(history_messages)

    await append_message(client, conv_id, "user", body.message)

    effective_plant_id = conversation.plant_id
    bundle = await build_plant_context(
        client,
        effective_plant_id,
        max_plants=settings.context_max_plants,
        max_entries=settings.context_max_recent_entries,
    )
    context_str = format_context_for_gemini(bundle, user_name=user.display_name)
    if history_block:
        context_str = f"{history_block}\n\n{context_str}"

    try:
        result = await call_gemini(
            message=body.message,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_output_tokens,
            context=context_str,
            response_schema=ACTION_RESPONSE_SCHEMA,
        )
    except UpstreamError:
        _log_failed(start, user.sub, conv_id)
        raise

    if not isinstance(result, dict):
        raise UpstreamError(_UPSTREAM_MSG)

    reply = str(result.get("reply", ""))
    proposed_action = build_proposed_action(result, effective_plant_id, user.sub, settings)
    vision_request = _build_vision_request(result, effective_plant_id)

    await append_message(client, conv_id, "assistant", reply)

    if was_empty and is_new and conversation.title == _DEFAULT_TITLE:
        derived = derive_title(body.message, settings.conversation_title_max_chars)
        if derived is not None:
            await set_title(client, conv_id, derived)

    await bump_updated_at(client, conv_id)

    _log_complete(start, user.sub, conv_id)

    return ChatResponse(
        conversation_id=conv_id,
        reply=reply,
        proposed_action=proposed_action,
        vision_request=vision_request,
    )


def _log_failed(start: float, user_sub: str, conversation_id: str) -> None:
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_failed",
        method="POST",
        path="/chat/stream",
        status=502,
        duration_ms=elapsed_ms,
        user=user_sub,
        conversation_id=conversation_id,
    )


def _log_complete(start: float, user_sub: str, conversation_id: str) -> None:
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_complete",
        method="POST",
        path="/chat/stream",
        status=200,
        duration_ms=elapsed_ms,
        user=user_sub,
        conversation_id=conversation_id,
    )


def _build_response(conv_id: str, reply: str, proposed_action, vision_request) -> dict:
    return {
        "conversation_id": conv_id,
        "reply": reply,
        "proposed_action": proposed_action.model_dump() if proposed_action else None,
        "vision_request": vision_request.model_dump() if vision_request else None,
    }
