from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.actions.models import ProposedActionResponse


class ImageRef(BaseModel):
    kind: Literal["journal_entry", "plant_latest"]
    journal_entry_id: str | None = None
    plant_id: str | None = None


class VisionRequest(BaseModel):
    reason_es: str
    suggested_ref: ImageRef


class VisionSpeciesCandidate(BaseModel):
    name: str
    confidence: Literal["alta", "media", "baja"]


class VisionNeedsMoreInfo(BaseModel):
    question_es: str | None = None


class VisionAnalysis(BaseModel):
    kind: Literal["health", "identify", "mixed", "declined"]
    diagnosis: str | None = None
    possible_species: list[VisionSpeciesCandidate] = Field(default_factory=list)
    confidence: Literal["alta", "media", "baja"] | None = None
    needs_more_info: VisionNeedsMoreInfo | None = None


class VisionAnalyzeRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    plant_id: str | None = None
    image_ref: ImageRef


class VisionAnalyzeResponse(BaseModel):
    reply: str
    vision: VisionAnalysis
    proposed_action: ProposedActionResponse | None = None


VISION_RESPONSE_SCHEMA: dict[str, Any] = {
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
                "payload": {
                    "type": "OBJECT",
                    "properties": {
                        "frequency_days": {"type": "NUMBER"},
                        "next_due_at": {"type": "STRING"},
                        "last_watered_at": {"type": "STRING"},
                        "notify_time": {"type": "STRING"},
                        "content": {"type": "STRING"},
                    },
                },
            },
            "required": ["action_type", "plant_id", "title", "summary_es", "payload"],
        },
        "vision": {
            "type": "OBJECT",
            "properties": {
                "kind": {
                    "type": "STRING",
                    "enum": ["health", "identify", "mixed", "declined"],
                },
                "diagnosis": {"type": "STRING", "nullable": True},
                "possible_species": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING"},
                            "confidence": {
                                "type": "STRING",
                                "enum": ["alta", "media", "baja"],
                            },
                        },
                        "required": ["name", "confidence"],
                    },
                },
                "confidence": {
                    "type": "STRING",
                    "enum": ["alta", "media", "baja"],
                    "nullable": True,
                },
                "needs_more_info": {
                    "type": "OBJECT",
                    "properties": {"question_es": {"type": "STRING"}},
                    "nullable": True,
                },
            },
            "required": ["kind"],
        },
    },
    "required": ["reply", "vision"],
}
