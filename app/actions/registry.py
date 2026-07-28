from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel  # noqa: TC002

from app.actions.models import PAYLOAD_MODELS, TABLE_MAP


@dataclass
class ActionSpec:
    action_type: str
    table: str
    operation: str
    payload_model: type[BaseModel]


def resolve_action(action_type: str) -> ActionSpec | None:
    model = PAYLOAD_MODELS.get(action_type)
    table = TABLE_MAP.get(action_type)
    if model is None or table is None:
        return None
    return ActionSpec(
        action_type=action_type,
        table=table,
        operation="insert",
        payload_model=model,
    )
