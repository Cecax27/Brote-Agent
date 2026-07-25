import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.agent.loop import call_gemini
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


class ChatResponse(BaseModel):
    reply: str


class HealthResponse(BaseModel):
    status: str


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

    access_token = request.headers["authorization"].removeprefix("Bearer ").strip()
    client = await build_user_client(settings.supabase_url, access_token)

    bundle = await build_plant_context(
        client,
        body.plant_id,
        max_plants=settings.context_max_plants,
        max_entries=settings.context_max_recent_entries,
    )
    context_str = format_context_for_gemini(bundle)

    reply = await call_gemini(
        message=body.message,
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
        context=context_str,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "request_complete",
        method="POST",
        path="/chat",
        status=200,
        duration_ms=elapsed_ms,
        user=user.sub,
    )
    return ChatResponse(reply=reply)
