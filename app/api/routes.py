import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError

from app.actions.models import ProposedActionResponse
from app.actions.registry import resolve_action
from app.actions.tokens import issue_confirm_token
from app.agent.loop import UpstreamError, call_gemini
from app.auth.dependency import UserIdentity, get_authenticated_user
from app.logging import get_logger
from app.supabase.client import build_user_client
from app.supabase.context import build_plant_context, format_context_for_gemini
from app.vision.models import ImageRef, VisionRequest

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter()

_UPSTREAM_MSG = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    plant_id: str | None = Field(default=None)


class ChatResponse(BaseModel):
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

    bundle = await build_plant_context(
        client,
        body.plant_id,
        max_plants=settings.context_max_plants,
        max_entries=settings.context_max_recent_entries,
    )
    context_str = format_context_for_gemini(bundle)

    result = await call_gemini(
        message=body.message,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
        context=context_str,
        response_schema=ACTION_RESPONSE_SCHEMA,
    )

    if not isinstance(result, dict):
        logger.error("gemini_unexpected_result_type", type=type(result).__name__)
        raise UpstreamError(_UPSTREAM_MSG)

    reply = str(result.get("reply", ""))
    proposed_action = _build_proposed_action(result, body.plant_id, user.sub, settings)
    vision_request = _build_vision_request(result, body.plant_id)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_complete",
        method="POST",
        path="/chat",
        status=200,
        duration_ms=elapsed_ms,
        user=user.sub,
    )
    return ChatResponse(reply=reply, proposed_action=proposed_action, vision_request=vision_request)


def _build_proposed_action(
    result: dict[str, Any],
    plant_id: str | None,
    user_sub: str,
    settings: "Settings",
) -> ProposedActionResponse | None:
    raw = result.get("proposed_action")
    if raw is None:
        return None

    if not isinstance(raw, dict):
        return None

    action_type = str(raw.get("action_type", ""))
    spec = resolve_action(action_type)
    if spec is None:
        return None

    try:
        payload_model = spec.payload_model(**raw.get("payload", {}))
    except ValidationError:
        return None

    action_plant_id = str(raw.get("plant_id", ""))
    if plant_id is not None and action_plant_id != plant_id:
        logger.warning(
            "proposed_action_plant_mismatch",
            proposal_plant=action_plant_id,
            request_plant=plant_id,
        )
        return None

    payload_dict = payload_model.model_dump()
    token = issue_confirm_token(
        action_type=action_type,
        plant_id=action_plant_id,
        payload=payload_dict,
        user_sub=user_sub,
        signing_secret=settings.action_signing_secret,
        ttl_seconds=settings.action_token_ttl_seconds,
    )

    return ProposedActionResponse(
        action_type=action_type,
        plant_id=action_plant_id,
        title=str(raw.get("title", "")),
        summary_es=str(raw.get("summary_es", "")),
        payload=payload_dict,
        confirm_token=token,
    )


def _build_vision_request(
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
