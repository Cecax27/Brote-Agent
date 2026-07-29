from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    conversation_id: str = Field(alias="id")
    user_id: str
    plant_id: str | None = None
    title: str = "Conversación con Flora"
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    photo_url: str | None = None


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    plant_id: str | None = None
    updated_at: datetime
    created_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    messages: list[Message]


class CreateConversationRequest(BaseModel):
    plant_id: str | None = Field(default=None)
    title: str | None = Field(default=None, max_length=200)


class CreateConversationResponse(BaseModel):
    conversation_id: str
