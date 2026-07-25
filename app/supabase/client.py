from __future__ import annotations

from supabase import create_async_client
from supabase._async.client import AsyncClient

from app.agent.loop import UpstreamError
from app.logging import get_logger

logger = get_logger(__name__)


async def build_user_client(url: str, access_token: str) -> AsyncClient:
    try:
        client = await create_async_client(url, access_token)
    except Exception as exc:
        logger.exception("supabase_client_create_failed")
        raise UpstreamError(
            "El servicio de datos no respondió. Inténtalo de nuevo en un momento."
        ) from exc

    logger.info("supabase_client_created")
    return client
