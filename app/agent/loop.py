from openai import AsyncOpenAI

from app.agent.prompts import SYSTEM_PROMPT
from app.logging import get_logger

logger = get_logger(__name__)


async def call_openai(message: str, api_key: str, model: str) -> str:
    client = AsyncOpenAI(api_key=api_key)
    logger.info("openai_call_start", model=model)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        temperature=0.7,
        max_tokens=1024,
    )

    content = response.choices[0].message.content or ""
    logger.info("openai_call_done", model=model)
    return content.strip()
