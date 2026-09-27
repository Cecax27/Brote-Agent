from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT
from app.logging import get_logger

logger = get_logger(__name__)

UPSTREAM_ERROR_MESSAGE = "El servicio de IA no respondió. Inténtalo de nuevo en un momento."

# How many characters of the failing content to include in the warning log.
# Truncated to avoid spamming logs with multi-KB structured payloads.
_PARSE_FAIL_PREVIEW_CHARS = 500


class UpstreamError(Exception):
    """Gemini API returned an error."""


async def _generate_once(
    *,
    client: genai.Client,
    model: str,
    contents: Any,  # noqa: ANN401
    config_kwargs: dict,
) -> str:
    """Run a single Gemini generate_content call. Returns the raw text."""
    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return (response.text or "").strip()


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
        content = await _generate_once(
            client=client,
            model=model,
            contents=contents,
            config_kwargs=config_kwargs,
        )
    except Exception as exc:
        logger.exception("gemini_call_failed", model=model)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from exc

    if response_schema is None:
        logger.info("gemini_call_done", model=model)
        return content

    # JSON-mode call: parse the response. On JSONDecodeError, retry with
    # a larger `max_output_tokens` budget — the usual cause is the model
    # running out of output tokens mid-string. Two escalation steps:
    # first retry at 2x, second retry at 4x.
    parsed = _try_parse_json(content, model)
    if parsed is not None:
        logger.info("gemini_call_done", model=model)
        return parsed

    # First attempt failed to parse. Retry with more headroom (2x).
    first_retry_tokens = max_output_tokens * 2
    logger.warning(
        "gemini_json_parse_failed_preview",
        model=model,
        attempt=1,
        content_length=len(content),
        content_preview=content[:_PARSE_FAIL_PREVIEW_CHARS],
        retry_max_output_tokens=first_retry_tokens,
    )
    content = await _retry_generate(
        client=client,
        model=model,
        contents=contents,
        config_kwargs=config_kwargs,
        max_output_tokens=first_retry_tokens,
    )

    parsed_retry1 = _try_parse_json(content, model)
    if parsed_retry1 is not None:
        logger.info("gemini_call_done_after_retry", model=model, attempt=2)
        return parsed_retry1

    # Second retry failed too — escalate to 4x.
    second_retry_tokens = max_output_tokens * 4
    logger.warning(
        "gemini_json_parse_failed_preview",
        model=model,
        attempt=2,
        content_length=len(content),
        content_preview=content[:_PARSE_FAIL_PREVIEW_CHARS],
        retry_max_output_tokens=second_retry_tokens,
    )
    content = await _retry_generate(
        client=client,
        model=model,
        contents=contents,
        config_kwargs=config_kwargs,
        max_output_tokens=second_retry_tokens,
    )

    parsed_retry2 = _try_parse_json(content, model)
    if parsed_retry2 is None:
        # All retries failed — give up with the standard 502 message.
        logger.error(
            "gemini_json_parse_failed_after_retry",
            model=model,
            content_length=len(content),
            content_preview=content[:_PARSE_FAIL_PREVIEW_CHARS],
        )
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)

    logger.info("gemini_call_done_after_retry", model=model, attempt=3)
    return parsed_retry2


async def _retry_generate(  # noqa: PLR0913
    *,
    client: genai.Client,
    model: str,
    contents: Any,  # noqa: ANN401
    config_kwargs: dict,
    max_output_tokens: int,
) -> str:
    """Run a single retry with overridden max_output_tokens. Raises UpstreamError."""
    retry_kwargs = dict(config_kwargs)
    retry_kwargs["max_output_tokens"] = max_output_tokens
    try:
        return await _generate_once(
            client=client,
            model=model,
            contents=contents,
            config_kwargs=retry_kwargs,
        )
    except Exception as exc:
        logger.exception("gemini_retry_call_failed", model=model)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from exc


def _try_parse_json(content: str, model: str) -> dict | None:  # noqa: ARG001
    """Parse `content` as JSON. Return the dict on success, None on parse error.

    Raises UpstreamError if the parsed value is not a dict (an unexpected
    shape — should not happen with a valid response_schema, but be strict).
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        logger.warning("gemini_unexpected_response_type", type=type(parsed).__name__)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    return parsed
