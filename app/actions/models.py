from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class CreateWateringSchedulePayload(BaseModel):
    frequency_days: int = Field(ge=1)
    last_watered_at: str | None = None
    next_due_at: str
    notify_time: str | None = None


class AddJournalEntryPayload(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "create_watering_schedule": CreateWateringSchedulePayload,
    "add_journal_entry": AddJournalEntryPayload,
}

TABLE_MAP: dict[str, str] = {
    "create_watering_schedule": "watering_schedules",
    "add_journal_entry": "journal_entries",
}


def payload_digest(payload: dict[str, Any], plant_id: str) -> str:
    import hashlib

    canonical = json.dumps({"payload": payload, "plant_id": plant_id}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
