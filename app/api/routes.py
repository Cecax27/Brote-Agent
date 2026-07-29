import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.actions.helpers import build_proposed_action
from app.actions.models import ProposedActionResponse
from app.agent.loop import UpstreamError, call_gemini
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
from app.logging import get_logger
from app.supabase.client import build_user_client
from app.supabase.context import build_plant_context, format_context_for_gemini
from app.vision.models import ImageRef, VisionRequest

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter()

_UPSTREAM_MSG = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."
_DEFAULT_CONVERSATION_TITLE = "Conversación con Flora"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    plant_id: str | None = Field(default=None)
    conversation_id: UUID | None = Field(default=None)


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    proposed_action: ProposedActionResponse | None = None
    vision_request: VisionRequest | None = None


class HealthResponse(BaseModel):
    status: str


ACTION_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "frequency_days": {
            "type": "NUMBER",
            "description": "Días entre riegos. Requerido para create_watering_schedule.",
        },
        "next_due_at": {
            "type": "STRING",
            "description": "Fecha del próximo riego ISO8601. Requerido para create_watering_schedule.",
        },
        "last_watered_at": {
            "type": "STRING",
            "description": "Fecha del último riego ISO8601. Opcional, solo para create_watering_schedule.",
        },
        "notify_time": {
            "type": "STRING",
            "description": "Hora de notificación HH:MM:SS. Opcional, solo para create_watering_schedule.",
        },
        "content": {
            "type": "STRING",
            "description": "Texto del consejo a guardar. Requerido para add_journal_entry.",
        },
    },
}

ACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "reply": {"type": "STRING"},
        "proposed_action": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {
                "action_type": {
                    "type": "STRING",
                    "enum": ["create_watering_schedule", "add_journal_entry"],
                },
                "plant_id": {
                    "type": "STRING",
                    "description": "UUID de la planta tal como aparece en el contexto (id: ...).",
                },
                "title": {"type": "STRING"},
                "summary_es": {"type": "STRING"},
                "payload": ACTION_PAYLOAD_SCHEMA,
            },
            "required": ["action_type", "plant_id", "title", "summary_es", "payload"],
        },
        "vision_request": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {
                "reason_es": {"type": "STRING"},
                "suggested_ref": {
                    "type": "OBJECT",
                    "properties": {
                        "kind": {
                            "type": "STRING",
                            "enum": ["journal_entry", "plant_latest"],
                        },
                        "journal_entry_id": {"type": "STRING", "nullable": True},
                        "plant_id": {"type": "STRING", "nullable": True},
                    },
                    "required": ["kind"],
                },
            },
            "required": ["reason_es", "suggested_ref"],
        },
    },
    "required": ["reply"],
}


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),  # noqa: B008, FAST002
) -> ChatResponse:
    settings: "Settings" = request.app.state.settings
    start = time.monotonic()

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    # 1. Resolve conversation
    is_new_conversation = body.conversation_id is None
    if is_new_conversation:
        conversation = await create_conversation(
            client,
            user.sub,
            plant_id=body.plant_id,
            title=None,
        )
    else:
        conversation = await get_conversation(
            client,
            str(body.conversation_id),
        )
        if conversation is None:
            raise ConversationNotFoundError(str(body.conversation_id))

    conv_id = conversation.conversation_id

    # 2. Plant scoping
    if (
        conversation.plant_id is not None
        and body.plant_id is not None
        and conversation.plant_id != body.plant_id
    ):
        raise ConversationPlantMismatchError

    if conversation.plant_id is None and body.plant_id is not None:
        await set_plant_id_once(client, conv_id, body.plant_id)
        conversation.plant_id = body.plant_id

    # 3. Load history (before persisting current turn)
    history_messages = await fetch_history(
        client,
        conv_id,
        settings.history_max_messages,
    )
    was_empty_history = len(history_messages) == 0
    history_messages = trim_to_budget(
        history_messages,
        settings.history_max_messages,
        settings.history_max_chars,
    )
    history_block = format_history_block(history_messages)

    # 4. Persist user message (before Gemini)
    await append_message(client, conv_id, "user", body.message)

    # 5. Build context (key off conversation's plant_id)
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

    # 6. Gemini
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
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request_failed",
            method="POST",
            path="/chat",
            status=502,
            duration_ms=elapsed_ms,
            user=user.sub,
            conversation_id=conv_id,
        )
        raise

    if not isinstance(result, dict):
        logger.error("gemini_unexpected_result_type", type=type(result).__name__)
        raise UpstreamError(_UPSTREAM_MSG)

    reply = str(result.get("reply", ""))
    proposed_action = build_proposed_action(result, effective_plant_id, user.sub, settings)
    vision_request = _build_vision_request(result, effective_plant_id)

    # 7. Persist assistant
    await append_message(client, conv_id, "assistant", reply)

    # 8. Auto-title on first user message of a default-titled conversation
    if (
        was_empty_history
        and is_new_conversation
        and conversation.title == _DEFAULT_CONVERSATION_TITLE
    ):
        derived = derive_title(body.message, settings.conversation_title_max_chars)
        if derived is not None:
            await set_title(client, conv_id, derived)

    # 9. Bump updated_at
    await bump_updated_at(client, conv_id)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_complete",
        method="POST",
        path="/chat",
        status=200,
        duration_ms=elapsed_ms,
        user=user.sub,
        conversation_id=conv_id,
    )
    return ChatResponse(
        conversation_id=conv_id,
        reply=reply,
        proposed_action=proposed_action,
        vision_request=vision_request,
    )


def _build_vision_request(  # noqa: PLR0911
    result: dict[str, Any],
    plant_id: str | None,
) -> VisionRequest | None:
    raw = result.get("vision_request")
    if raw is None:
        return None

    if not isinstance(raw, dict):
        return None

    suggested_raw = raw.get("suggested_ref")
    if not isinstance(suggested_raw, dict):
        return None

    kind = str(suggested_raw.get("kind", ""))
    if kind not in ("journal_entry", "plant_latest"):
        return None

    reason_es = str(raw.get("reason_es", ""))

    if kind == "journal_entry":
        journal_entry_id = str(suggested_raw.get("journal_entry_id", "") or "")
        if not journal_entry_id:
            return None
        suggested_ref = ImageRef(kind=kind, journal_entry_id=journal_entry_id)
    else:
        ref_plant_id = str(suggested_raw.get("plant_id", "") or "")
        if not ref_plant_id:
            return None
        if plant_id is not None and ref_plant_id != plant_id:
            logger.warning(
                "vision_request_plant_mismatch",
                vision_plant=ref_plant_id,
                request_plant=plant_id,
            )
            return None
        suggested_ref = ImageRef(kind=kind, plant_id=ref_plant_id)

    return VisionRequest(reason_es=reason_es, suggested_ref=suggested_ref)
