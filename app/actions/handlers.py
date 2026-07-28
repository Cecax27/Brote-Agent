from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.loop import UpstreamError
from app.logging import get_logger
from app.supabase.schema import TABLE_JOURNAL_ENTRIES, TABLE_WATERING_SCHEDULES

if TYPE_CHECKING:
    from supabase._async.client import AsyncClient

logger = get_logger(__name__)

_UPSTREAM_MSG = "El servicio de datos no respondió. Inténtalo de nuevo en un momento."


async def create_watering_schedule(
    client: "AsyncClient",
    plant_id: str,
    user_sub: str,
    payload: dict,
) -> str:
    try:
        await (
            client.table(TABLE_WATERING_SCHEDULES)
            .update({"active": False})
            .eq("plant_id", plant_id)
            .eq("active", True)  # noqa: FBT003
            .execute()
        )
    except Exception as exc:
        logger.exception("watering_schedule_deactivate_failed")
        raise UpstreamError(_UPSTREAM_MSG) from exc

    row = {
        "plant_id": plant_id,
        "user_id": user_sub,
        "frequency_days": payload["frequency_days"],
        "next_due_at": payload["next_due_at"],
        "active": True,
    }
    if payload.get("last_watered_at"):
        row["last_watered_at"] = payload["last_watered_at"]
    if payload.get("notify_time"):
        row["notify_time"] = payload["notify_time"]

    try:
        result = await client.table(TABLE_WATERING_SCHEDULES).insert(row).execute()
    except Exception as exc:
        logger.exception("watering_schedule_insert_failed")
        raise UpstreamError(_UPSTREAM_MSG) from exc

    rows = result.data or []
    if not rows:
        raise UpstreamError(_UPSTREAM_MSG)
    return str(rows[0]["id"])


async def add_journal_entry(
    client: "AsyncClient",
    plant_id: str,
    user_sub: str,
    payload: dict,
) -> str:
    row = {
        "plant_id": plant_id,
        "user_id": user_sub,
        "type": "observation",
        "content": payload["content"],
    }

    try:
        result = await client.table(TABLE_JOURNAL_ENTRIES).insert(row).execute()
    except Exception as exc:
        logger.exception("journal_entry_insert_failed")
        raise UpstreamError(_UPSTREAM_MSG) from exc

    rows = result.data or []
    if not rows:
        raise UpstreamError(_UPSTREAM_MSG)
    return str(rows[0]["id"])
