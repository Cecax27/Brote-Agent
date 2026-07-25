import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agent.loop import call_openai
from app.logging import get_logger

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str


class HealthResponse(BaseModel):
    status: str


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    settings: "Settings" = request.app.state.settings
    start = time.monotonic()

    reply = await call_openai(
        message=body.message,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("request_complete", method="POST", path="/chat", status=200, duration_ms=elapsed_ms)
    return ChatResponse(reply=reply)
