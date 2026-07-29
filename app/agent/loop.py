from __future__ import annotations

import json

from google import genai
from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT
from app.logging import get_logger

logger = get_logger(__name__)

UPSTREAM_ERROR_MESSAGE = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."


class UpstreamError(Exception):
    """Gemini API returned an error."""


async def call_gemini(
    message: str,
    api_key: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    *,
    context: str | None = None,
    response_schema: dict | None = None,
) -> str | dict:
    client = genai.Client(api_key=api_key)
    logger.info("gemini_call_start", model=model, has_context=context is not None)

    contents = message
    if context:
        contents = f"{context}\n\nMensaje del usuario: {message}"

    config_kwargs: dict = {
        "system_instruction": SYSTEM_PROMPT,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as exc:
        logger.exception("gemini_call_failed", model=model)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from exc

    content = (response.text or "").strip()

    if response_schema is not None:
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                logger.warning("gemini_unexpected_response_type", type=type(parsed).__name__)
                raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
            logger.info("gemini_call_done", model=model)
            return parsed
        except json.JSONDecodeError:
            logger.exception("gemini_json_parse_failed")
            raise UpstreamError(UPSTREAM_ERROR_MESSAGE)

    logger.info("gemini_call_done", model=model)
    return content
