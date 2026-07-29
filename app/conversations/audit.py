from __future__ import annotations

from app.logging import get_logger

logger = get_logger(__name__)


def log_conversation_event(
    *,
    event_type: str,
    conversation_id: str | None,
    user_sub: str,
    count: int | None = None,
    status: int = 200,
    duration_ms: int | None = None,
) -> None:
    logger.info(
        "conversation_event",
        event_type=event_type,
        conversation_id=conversation_id,
        user=user_sub,
        count=count,
        status=status,
        duration_ms=duration_ms,
    )
