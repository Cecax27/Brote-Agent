from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from app.agent.loop import UpstreamError
from app.config.settings import Settings  # noqa: TC001
from app.logging import get_logger
from app.supabase import schema as s

if TYPE_CHECKING:
    from supabase._async.client import AsyncClient

logger = get_logger(__name__)

_PHOTO_FETCH_UPSTREAM = "El servicio de fotos no respondió. Inténtalo de nuevo en un momento."
_PHOTO_TOO_LARGE = "La foto es demasiado grande para analizarla."


class ImageNotFoundError(Exception):
    pass


@dataclass
class ResolvedPhoto:
    url: str
    mime_hint: str | None = None


async def resolve_journal_photo(
    client: "AsyncClient", journal_entry_id: str
) -> ResolvedPhoto | None:
    result = (
        await client.table(s.TABLE_JOURNAL_ENTRIES)
        .select(s.COL_PHOTO_URL)
        .eq(s.COL_ID, journal_entry_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    url: str | None = result.data[0].get(s.COL_PHOTO_URL)
    if not url:
        return None
    return ResolvedPhoto(url=url)


async def resolve_plant_latest_photo(client: "AsyncClient", plant_id: str) -> ResolvedPhoto | None:
    plant_result = (
        await client.table(s.TABLE_PLANTS)
        .select(s.COL_PHOTO_URL)
        .eq(s.COL_ID, plant_id)
        .limit(1)
        .execute()
    )
    if plant_result.data:
        url: str | None = plant_result.data[0].get(s.COL_PHOTO_URL)
        if url:
            return ResolvedPhoto(url=url)

    journal_result = (
        await client.table(s.TABLE_JOURNAL_ENTRIES)
        .select(s.COL_PHOTO_URL)
        .eq(s.COL_PLANT_ID, plant_id)
        .not_.is_(s.COL_PHOTO_URL, "null")
        .order(s.COL_CREATED_AT, desc=True)
        .limit(1)
        .execute()
    )
    if journal_result.data:
        url = journal_result.data[0].get(s.COL_PHOTO_URL)
        if url:
            return ResolvedPhoto(url=url)

    return None


async def fetch_photo_bytes(url: str, settings: Settings) -> bytes:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as http_client:
            response = await http_client.get(url)
            if response.status_code != 200:
                logger.warning(
                    "photo_fetch_bad_status",
                    status_code=response.status_code,
                )
                raise UpstreamError(_PHOTO_FETCH_UPSTREAM)  # noqa: TRY301
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > settings.vision_max_download_bytes:
                raise UpstreamError(_PHOTO_TOO_LARGE)  # noqa: TRY301
            raw = response.content
            if len(raw) > settings.vision_max_download_bytes:
                raise UpstreamError(_PHOTO_TOO_LARGE)  # noqa: TRY301
            return raw
    except UpstreamError:
        raise
    except Exception as exc:
        logger.exception("photo_fetch_failed")
        raise UpstreamError(_PHOTO_FETCH_UPSTREAM) from exc
