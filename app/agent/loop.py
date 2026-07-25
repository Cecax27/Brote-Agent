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
) -> str:
    client = genai.Client(api_key=api_key)
    logger.info("gemini_call_start", model=model)

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as exc:
        logger.exception("gemini_call_failed", model=model)
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from exc

    content = response.text or ""
    logger.info("gemini_call_done", model=model)
    return content.strip()
