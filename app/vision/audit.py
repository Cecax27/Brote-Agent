from __future__ import annotations

from app.logging import get_logger

logger = get_logger(__name__)


def log_vision_call(
    *,
    endpoint: str,
    source: str,
    plant_id: str | None,
    user_sub: str,
    mime_type: str | None,
    original_bytes: int,
    resized_bytes: int,
    max_dimension: int,
    gemini_model: str,
    vision_kind: str | None,
    confidence: str | None,
    status: str,
    duration_ms: int,
    proposed_action_type: str | None,
) -> None:
    logger.info(
        "vision_call",
        endpoint=endpoint,
        source=source,
        plant_id=plant_id,
        user=user_sub,
        mime_type=mime_type,
        original_bytes=original_bytes,
        resized_bytes=resized_bytes,
        max_dimension=max_dimension,
        gemini_model=gemini_model,
        vision_kind=vision_kind,
        confidence=confidence,
        status=status,
        duration_ms=duration_ms,
        proposed_action_type=proposed_action_type,
    )
