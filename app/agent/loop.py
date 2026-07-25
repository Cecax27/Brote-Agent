from google import genai
from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT
from app.logging import get_logger

logger = get_logger(__name__)


async def call_gemini(message: str, api_key: str, model: str) -> str:
    client = genai.Client(api_key=api_key)
    logger.info("gemini_call_start", model=model)

    response = await client.aio.models.generate_content(
        model=model,
        contents=message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=1024,
        ),
    )

    content = response.text or ""
    logger.info("gemini_call_done", model=model)
    return content.strip()
