from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def log_action_executed(  # noqa: PLR0913
    *,
    action_type: str,
    table: str,
    plant_id: str,
    action_id: str | None,
    user_sub: str,
    status: str,
    duration_ms: int,
    payload_digest: str,
) -> None:
    logger.info(
        "action_executed",
        action_type=action_type,
        table=table,
        plant_id=plant_id,
        action_id=action_id,
        user=user_sub,
        status=status,
        duration_ms=duration_ms,
        payload_digest=payload_digest,
    )
