from __future__ import annotations

from app.conversations.models import Message

HISTORY_HEADER = "Historial de la conversación"


def format_history_block(messages: list[Message]) -> str:
    if not messages:
        return ""

    lines = [HISTORY_HEADER]
    for msg in messages:
        if not msg.content.strip():
            continue
        label = "Usuario" if msg.role == "user" else "Flora"
        lines.append(f"{label}: {msg.content}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def trim_to_budget(
    messages: list[Message],
    max_messages: int,
    max_chars: int,
) -> list[Message]:
    trimmed = list(messages)

    while len(trimmed) > max_messages:
        trimmed.pop(0)

    total = sum(len(m.content) for m in trimmed)
    while total > max_chars and len(trimmed) > 1:
        total -= len(trimmed[0].content)
        trimmed.pop(0)

    return trimmed
