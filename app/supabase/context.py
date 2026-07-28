from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.agent.loop import UpstreamError
from app.logging import get_logger
from app.supabase import schema as s

if TYPE_CHECKING:
    from supabase._async.client import AsyncClient

logger = get_logger(__name__)


@dataclass
class PlantSummary:
    id: str
    name: str | None
    species: str | None
    last_watered_at: str | None = None
    next_due_at: str | None = None


@dataclass
class JournalEntry:
    created_at: str | None
    type: str | None
    content: str | None
    photo_url: str | None = None


@dataclass
class LightMeasurementEntry:
    created_at: str | None
    device_lux: float | None = None
    calibrated_lux: float | None = None
    light_profile: str | None = None
    notes: str | None = None


@dataclass
class DeepPlantContext:
    plant: PlantSummary | None
    watering_schedule: WateringSchedule | None = None
    journal: list[JournalEntry] = field(default_factory=list)
    light: list[LightMeasurementEntry] = field(default_factory=list)
    photo_count: int = 0


@dataclass
class WateringSchedule:
    frequency_days: int | None = None
    last_watered_at: str | None = None
    next_due_at: str | None = None
    active: bool | None = None


@dataclass
class ContextBundle:
    light: list[PlantSummary] | None = None
    deep: DeepPlantContext | None = None


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("T")[0] if "T" in value else value


async def _fetch_light_context(
    client: AsyncClient, max_plants: int
) -> list[PlantSummary]:
    result = (
        await client.table(s.TABLE_PLANTS)
        .select(
            f"{s.COL_ID}, {s.COL_NAME}, {s.COL_SPECIES}"
        )
        .limit(max_plants)
        .execute()
    )

    plants: list[PlantSummary] = []
    for row in result.data:
        plants.append(
            PlantSummary(
                id=row[s.COL_ID],
                name=row.get(s.COL_NAME),
                species=row.get(s.COL_SPECIES),
            )
        )

    if plants:
        schedule_result = (
            await client.table(s.TABLE_WATERING_SCHEDULES)
            .select(
                f"{s.COL_PLANT_ID}, {s.COL_LAST_WATERED_AT}, "
                f"{s.COL_NEXT_DUE_AT}"
            )
            .eq(s.COL_ACTIVE, True)
            .execute()
        )
        schedule_by_plant: dict[str, dict] = {}
        for row in schedule_result.data:
            schedule_by_plant[row[s.COL_PLANT_ID]] = row

        for plant in plants:
            schedule = schedule_by_plant.get(plant.id)
            if schedule:
                plant.last_watered_at = _parse_iso_date(
                    schedule.get(s.COL_LAST_WATERED_AT)
                )
                plant.next_due_at = _parse_iso_date(
                    schedule.get(s.COL_NEXT_DUE_AT)
                )

    return plants


async def _fetch_deep_context(
    client: AsyncClient, plant_id: str, max_entries: int
) -> DeepPlantContext:
    plant_result = (
        await client.table(s.TABLE_PLANTS)
        .select(
            f"{s.COL_ID}, {s.COL_NAME}, {s.COL_SPECIES}"
        )
        .eq(s.COL_ID, plant_id)
        .limit(1)
        .execute()
    )

    plant: PlantSummary | None = None
    if plant_result.data:
        row = plant_result.data[0]
        plant = PlantSummary(
            id=row[s.COL_ID],
            name=row.get(s.COL_NAME),
            species=row.get(s.COL_SPECIES),
        )

    schedule: WateringSchedule | None = None
    schedule_result = (
        await client.table(s.TABLE_WATERING_SCHEDULES)
        .select(
            f"{s.COL_FREQUENCY_DAYS}, {s.COL_LAST_WATERED_AT}, "
            f"{s.COL_NEXT_DUE_AT}, {s.COL_ACTIVE}"
        )
        .eq(s.COL_PLANT_ID, plant_id)
        .limit(1)
        .execute()
    )
    if schedule_result.data:
        row = schedule_result.data[0]
        schedule = WateringSchedule(
            frequency_days=row.get(s.COL_FREQUENCY_DAYS),
            last_watered_at=_parse_iso_date(row.get(s.COL_LAST_WATERED_AT)),
            next_due_at=_parse_iso_date(row.get(s.COL_NEXT_DUE_AT)),
            active=row.get(s.COL_ACTIVE),
        )
        if plant:
            plant.last_watered_at = schedule.last_watered_at
            plant.next_due_at = schedule.next_due_at

    journal_entries: list[JournalEntry] = []
    journal_result = (
        await client.table(s.TABLE_JOURNAL_ENTRIES)
        .select(
            f"{s.COL_CREATED_AT}, {s.COL_TYPE}, {s.COL_CONTENT}, "
            f"{s.COL_PHOTO_URL}"
        )
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_CREATED_AT, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in journal_result.data:
        journal_entries.append(
            JournalEntry(
                created_at=_parse_iso_date(row.get(s.COL_CREATED_AT)),
                type=row.get(s.COL_TYPE),
                content=row.get(s.COL_CONTENT),
                photo_url=row.get(s.COL_PHOTO_URL),
            )
        )

    light_entries: list[LightMeasurementEntry] = []
    light_result = (
        await client.table(s.TABLE_LIGHT_MEASUREMENTS)
        .select(
            f"{s.COL_CREATED_AT}, {s.COL_DEVICE_LUX}, "
            f"{s.COL_CALIBRATED_LUX}, {s.COL_LIGHT_PROFILE}, {s.COL_NOTES}"
        )
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_CREATED_AT, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in light_result.data:
        light_entries.append(
            LightMeasurementEntry(
                created_at=_parse_iso_date(row.get(s.COL_CREATED_AT)),
                device_lux=row.get(s.COL_DEVICE_LUX),
                calibrated_lux=row.get(s.COL_CALIBRATED_LUX),
                light_profile=row.get(s.COL_LIGHT_PROFILE),
                notes=row.get(s.COL_NOTES),
            )
        )

    photo_count = 0
    photo_result = (
        await client.table(s.TABLE_JOURNAL_ENTRIES)
        .select(s.COL_ID, count="exact")
        .not_.is_(s.COL_PHOTO_URL, "null")
        .eq(s.COL_PLANT_ID, plant_id)
        .execute()
    )
    if hasattr(photo_result, "count") and photo_result.count is not None:
        photo_count = photo_result.count

    return DeepPlantContext(
        plant=plant,
        watering_schedule=schedule,
        journal=journal_entries,
        light=light_entries,
        photo_count=photo_count,
    )


async def build_plant_context(
    client: AsyncClient,
    plant_id: str | None,
    *,
    max_plants: int = 20,
    max_entries: int = 10,
) -> ContextBundle:
    start = time.monotonic()
    try:
        if plant_id:
            deep = await _fetch_deep_context(client, plant_id, max_entries)
            elapsed = int((time.monotonic() - start) * 1000)
            logger.info(
                "context_built",
                mode="deep",
                plant_id=plant_id,
                journal_count=len(deep.journal),
                light_count=len(deep.light),
                photo_count=deep.photo_count,
                duration_ms=elapsed,
            )
            return ContextBundle(deep=deep)

        light = await _fetch_light_context(client, max_plants)
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "context_built",
            mode="light",
            plant_count=len(light),
            duration_ms=elapsed,
        )
        return ContextBundle(light=light)

    except UpstreamError:
        raise
    except Exception as exc:
        logger.exception("supabase_read_failed")
        raise UpstreamError(
            "El servicio de datos no respondió. Inténtalo de nuevo en un momento."
        ) from exc


def format_context_for_gemini(bundle: ContextBundle) -> str:
    if bundle.deep is not None:
        return _format_deep_context(bundle.deep)
    if bundle.light is not None:
        return _format_light_context(bundle.light)
    return ""


def _format_light_context(plants: list[PlantSummary]) -> str:
    if not plants:
        return "[Contexto] El usuario no tiene plantas registradas todavía."

    lines = ["[Contexto — Resumen de todas las plantas del usuario]"]
    for p in plants:
        name = p.name or "Sin nombre"
        species = f" ({p.species})" if p.species else ""
        plant_id = p.id or "?"
        parts = [f"  - {name}{species} (id: {plant_id})"]
        if p.last_watered_at:
            parts.append(f" | último riego: {p.last_watered_at}")
        if p.next_due_at:
            parts.append(f" | próximo riego: {p.next_due_at}")
        lines.append("".join(parts))
    return "\n".join(lines)


def _format_deep_context(ctx: DeepPlantContext) -> str:
    if ctx.plant is None:
        return "[Contexto] Esta planta no se ha encontrado en tu jardín."

    p = ctx.plant
    name = p.name or "Sin nombre"
    species = f" ({p.species})" if p.species else ""
    plant_id = p.id or "?"
    lines = [f"[Contexto — {name}{species} — id: {plant_id}]"]
    if p.last_watered_at:
        lines.append(f"  Último riego: {p.last_watered_at}")
    if p.next_due_at:
        lines.append(f"  Próximo riego: {p.next_due_at}")

    _JOURNAL_LABELS: dict[str, str] = {
        "watering": "Historial de riego",
        "fertilizing": "Abonados",
        "repotting": "Trasplantes",
        "pruning": "Podas",
        "observation": "Observaciones",
    }

    grouped: dict[str, list[JournalEntry]] = {}
    for entry in ctx.journal:
        entry_type = entry.type or "observation"
        grouped.setdefault(entry_type, []).append(entry)

    for entry_type, label in _JOURNAL_LABELS.items():
        entries = grouped.get(entry_type)
        if not entries:
            continue
        lines.append(f"  {label}:")
        for e in entries:
            date = f"{e.created_at}: " if e.created_at else ""
            content = e.content or ""
            lines.append(f"    - {date}{content}")

    if ctx.light:
        lines.append("  Mediciones de luz:")
        for e in ctx.light:
            date = f"{e.created_at}: " if e.created_at else ""
            details = []
            if e.device_lux is not None:
                details.append(f"lux: {e.device_lux}")
            if e.calibrated_lux is not None:
                details.append(f"calibrado: {e.calibrated_lux}")
            if e.light_profile:
                details.append(e.light_profile)
            notes = e.notes or ""
            detail_str = f" ({', '.join(details)})" if details else ""
            lines.append(f"    - {date}{notes}{detail_str}")

    if ctx.photo_count > 0:
        lines.append(f"  Fotos en el diario: {ctx.photo_count}")

    return "\n".join(lines)
