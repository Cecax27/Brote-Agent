from __future__ import annotations

import json

from google import genai
from google.genai import types

from app.agent.prompts import VISION_SUB_PROMPT, SYSTEM_PROMPT
from app.config.settings import Settings
from app.logging import get_logger
from app.vision.models import VISION_RESPONSE_SCHEMA

logger = get_logger(__name__)

UPSTREAM_ERROR_MESSAGE = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."


class UpstreamError(Exception):
    pass


def _build_vision_system_prompt() -> str:
    return SYSTEM_PROMPT + "\n\n" + VISION_SUB_PROMPT


async def analyze_image_with_gemini(
    image_bytes: bytes,
    message: str,
    settings: Settings,
    *,
    context_str: str | None = None,
) -> dict:
    client = genai.Client(api_key=settings.gemini_api_key)
    model = settings.gemini_vision_model
    logger.info("vision_gemini_call_start", model=model, has_context=context_str is not None)

    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

    text_parts: list[str] = []
    if context_str:
        text_parts.append(context_str)
    text_parts.append(message)

    contents = [image_part] + text_parts  # type: ignore[assignment]

    system_prompt = _build_vision_system_prompt()

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=settings.gemini_vision_temperature,
                response_mime_type="application/json",
                response_schema=VISION_RESPONSE_SCHEMA,
            ),
        )
    except Exception as exc:
        logger.exception("vision_gemini_call_failed", model=model)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from exc

    content = (response.text or "").strip()
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            logger.warning("vision_gemini_unexpected_response_type", type=type(parsed).__name__)
            raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    except json.JSONDecodeError:
        logger.exception("vision_gemini_json_parse_failed")
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)

    logger.info("vision_gemini_call_done", model=model)
    return parsed
