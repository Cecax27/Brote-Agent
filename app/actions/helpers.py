from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.actions.models import ProposedActionResponse
from app.actions.registry import resolve_action
from app.actions.tokens import issue_confirm_token
from app.config.settings import Settings  # noqa: TC001
from app.logging import get_logger

logger = get_logger(__name__)


def build_proposed_action(
    result: dict[str, Any],
    plant_id: str | None,
    user_sub: str,
    settings: Settings,
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
