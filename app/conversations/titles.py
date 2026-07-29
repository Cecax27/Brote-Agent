from __future__ import annotations


def derive_title(first_user_message: str, max_chars: int) -> str | None:
    stripped = first_user_message.strip()
    if not stripped:
        return None

    if len(stripped) <= max_chars:
        return stripped

    truncated = stripped[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    return truncated + "…"
