import json
import time
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.actions.models import payload_digest
from app.actions.registry import resolve_action
from app.actions.tokens import issue_confirm_token
from app.agent.loop import UpstreamError, call_gemini
from app.auth.dependency import UserIdentity, get_authenticated_user
from app.logging import get_logger
from app.supabase.client import build_user_client
from app.supabase.context import build_plant_context, format_context_for_gemini

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    plant_id: str | None = Field(default=None)


class ProposedActionResponse(BaseModel):
    action_type: str
    plant_id: str
    title: str
    summary_es: str
    payload: dict[str, Any]
    confirm_token: str


class ChatResponse(BaseModel):
    reply: str
    proposed_action: ProposedActionResponse | None = None


class HealthResponse(BaseModel):
    status: str


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
                "plant_id": {"type": "STRING"},
                "title": {"type": "STRING"},
                "summary_es": {"type": "STRING"},
                "payload": {"type": "OBJECT"},
            },
            "required": ["action_type", "plant_id", "title", "summary_es", "payload"],
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
    user: UserIdentity = Depends(get_authenticated_user),
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
        raise UpstreamError("El servicio de IA no respondió. Inténtalo de nuevo en un momento.")

    reply = str(result.get("reply", ""))
    proposed_action = _build_proposed_action(result, body.plant_id, user.sub, settings)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_complete",
        method="POST",
        path="/chat",
        status=200,
        duration_ms=elapsed_ms,
        user=user.sub,
    )
    return ChatResponse(reply=reply, proposed_action=proposed_action)


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
    except Exception:
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
