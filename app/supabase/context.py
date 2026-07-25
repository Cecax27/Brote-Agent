from __future__ import annotations

import time
from dataclasses import dataclass, field

from supabase._async.client import AsyncClient

from app.agent.loop import UpstreamError
from app.logging import get_logger
from app.supabase import schema as s

logger = get_logger(__name__)


@dataclass
class PlantSummary:
    id: str
    nickname: str | None
    species: str | None
    last_watered: str | None
    next_watering: str | None


@dataclass
class WateringEntry:
    date: str | None
    notes: str | None


@dataclass
class LightEntry:
    date: str | None
    light_level: str | None
    notes: str | None


@dataclass
class FertilizationEntry:
    date: str | None
    fertilizer_type: str | None
    notes: str | None


@dataclass
class RepottingEntry:
    date: str | None
    soil_mix: str | None
    pot_size: str | None
    notes: str | None


@dataclass
class ObservationEntry:
    date: str | None
    notes: str | None


@dataclass
class LogEntry:
    date: str | None
    entry_type: str | None
    notes: str | None


@dataclass
class PhotoMetadata:
    count: int
    last_taken: str | None


@dataclass
class DeepPlantContext:
    plant: PlantSummary | None
    log: list[LogEntry] = field(default_factory=list)
    watering: list[WateringEntry] = field(default_factory=list)
    light: list[LightEntry] = field(default_factory=list)
    fertilizations: list[FertilizationEntry] = field(default_factory=list)
    repottings: list[RepottingEntry] = field(default_factory=list)
    observations: list[ObservationEntry] = field(default_factory=list)
    photos: PhotoMetadata | None = None


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
            f"{s.COL_ID}, {s.COL_NICKNAME}, {s.COL_SPECIES}, "
            f"{s.COL_LAST_WATERED}, {s.COL_NEXT_WATERING}"
        )
        .limit(max_plants)
        .execute()
    )

    plants: list[PlantSummary] = []
    for row in result.data:
        plants.append(
            PlantSummary(
                id=row[s.COL_ID],
                nickname=row.get(s.COL_NICKNAME),
                species=row.get(s.COL_SPECIES),
                last_watered=row.get(s.COL_LAST_WATERED),
                next_watering=row.get(s.COL_NEXT_WATERING),
            )
        )
    return plants


async def _fetch_deep_context(
    client: AsyncClient, plant_id: str, max_entries: int
) -> DeepPlantContext:
    plant_result = (
        await client.table(s.TABLE_PLANTS)
        .select(
            f"{s.COL_ID}, {s.COL_NICKNAME}, {s.COL_SPECIES}, "
            f"{s.COL_LAST_WATERED}, {s.COL_NEXT_WATERING}"
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
            nickname=row.get(s.COL_NICKNAME),
            species=row.get(s.COL_SPECIES),
            last_watered=row.get(s.COL_LAST_WATERED),
            next_watering=row.get(s.COL_NEXT_WATERING),
        )

    log_entries: list[LogEntry] = []
    log_result = (
        await client.table(s.TABLE_LOG)
        .select(f"{s.COL_DATE}, {s.COL_ENTRY_TYPE}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in log_result.data:
        log_entries.append(
            LogEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                entry_type=row.get(s.COL_ENTRY_TYPE),
                notes=row.get(s.COL_NOTES),
            )
        )

    watering_entries: list[WateringEntry] = []
    watering_result = (
        await client.table(s.TABLE_WATERING)
        .select(f"{s.COL_DATE}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in watering_result.data:
        watering_entries.append(
            WateringEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                notes=row.get(s.COL_NOTES),
            )
        )

    light_entries: list[LightEntry] = []
    light_result = (
        await client.table(s.TABLE_LIGHT)
        .select(f"{s.COL_DATE}, {s.COL_LIGHT_LEVEL}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in light_result.data:
        light_entries.append(
            LightEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                light_level=row.get(s.COL_LIGHT_LEVEL),
                notes=row.get(s.COL_NOTES),
            )
        )

    fert_entries: list[FertilizationEntry] = []
    fert_result = (
        await client.table(s.TABLE_FERTILIZATIONS)
        .select(f"{s.COL_DATE}, {s.COL_FERTILIZER_TYPE}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in fert_result.data:
        fert_entries.append(
            FertilizationEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                fertilizer_type=row.get(s.COL_FERTILIZER_TYPE),
                notes=row.get(s.COL_NOTES),
            )
        )

    repot_entries: list[RepottingEntry] = []
    repot_result = (
        await client.table(s.TABLE_REPOTTINGS)
        .select(f"{s.COL_DATE}, {s.COL_SOIL_MIX}, {s.COL_POT_SIZE}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in repot_result.data:
        repot_entries.append(
            RepottingEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                soil_mix=row.get(s.COL_SOIL_MIX),
                pot_size=row.get(s.COL_POT_SIZE),
                notes=row.get(s.COL_NOTES),
            )
        )

    obs_entries: list[ObservationEntry] = []
    obs_result = (
        await client.table(s.TABLE_OBSERVATIONS)
        .select(f"{s.COL_DATE}, {s.COL_NOTES}")
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_DATE, desc=True)
        .limit(max_entries)
        .execute()
    )
    for row in obs_result.data:
        obs_entries.append(
            ObservationEntry(
                date=_parse_iso_date(row.get(s.COL_DATE)),
                notes=row.get(s.COL_NOTES),
            )
        )

    photo_meta: PhotoMetadata | None = None
    photo_result = (
        await client.table(s.TABLE_PHOTOS)
        .select(s.COL_CREATED_AT)
        .eq(s.COL_PLANT_ID, plant_id)
        .order(s.COL_CREATED_AT, desc=True)
        .execute()
    )
    if photo_result.data:
        last_taken = _parse_iso_date(photo_result.data[0].get(s.COL_CREATED_AT))
        photo_meta = PhotoMetadata(count=len(photo_result.data), last_taken=last_taken)

    return DeepPlantContext(
        plant=plant,
        log=log_entries,
        watering=watering_entries,
        light=light_entries,
        fertilizations=fert_entries,
        repottings=repot_entries,
        observations=obs_entries,
        photos=photo_meta,
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
                log_count=len(deep.log),
                watering_count=len(deep.watering),
                light_count=len(deep.light),
                fert_count=len(deep.fertilizations),
                repot_count=len(deep.repottings),
                obs_count=len(deep.observations),
                photo_count=deep.photos.count if deep.photos else 0,
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
        name = p.nickname or "Sin nombre"
        species = f" ({p.species})" if p.species else ""
        parts = [f"  - {name}{species}"]
        if p.last_watered:
            parts.append(f" | último riego: {p.last_watered}")
        if p.next_watering:
            parts.append(f" | próximo riego: {p.next_watering}")
        lines.append("".join(parts))
    return "\n".join(lines)


def _format_deep_context(ctx: DeepPlantContext) -> str:
    if ctx.plant is None:
        return "[Contexto] Esta planta no se ha encontrado en tu jardín. "

    p = ctx.plant
    name = p.nickname or "Sin nombre"
    species = f" ({p.species})" if p.species else ""
    lines = [f"[Contexto — {name}{species}]"]
    if p.last_watered:
        lines.append(f"  Último riego: {p.last_watered}")
    if p.next_watering:
        lines.append(f"  Próximo riego: {p.next_watering}")

    if ctx.log:
        lines.append("  Últimas entradas del diario:")
        for e in ctx.log:
            date = f"{e.date}: " if e.date else ""
            entry_type = f" ({e.entry_type})" if e.entry_type else ""
            lines.append(f"    - {date}{e.notes or ''}{entry_type}")

    if ctx.watering:
        lines.append("  Historial de riego:")
        for e in ctx.watering:
            date = f"{e.date}: " if e.date else ""
            lines.append(f"    - {date}{e.notes or ''}")

    if ctx.light:
        lines.append("  Mediciones de luz:")
        for e in ctx.light:
            date = f"{e.date}: " if e.date else ""
            level = f" ({e.light_level})" if e.light_level else ""
            lines.append(f"    - {date}{e.notes or ''}{level}")

    if ctx.fertilizations:
        lines.append("  Abonados:")
        for e in ctx.fertilizations:
            date = f"{e.date}: " if e.date else ""
            fert = f" ({e.fertilizer_type})" if e.fertilizer_type else ""
            lines.append(f"    - {date}{e.notes or ''}{fert}")

    if ctx.repottings:
        lines.append("  Trasplantes:")
        for e in ctx.repottings:
            date = f"{e.date}: " if e.date else ""
            soil = f" (sustrato: {e.soil_mix})" if e.soil_mix else ""
            pot = f" (maceta: {e.pot_size})" if e.pot_size else ""
            lines.append(f"    - {date}{e.notes or ''}{soil}{pot}")

    if ctx.observations:
        lines.append("  Observaciones:")
        for e in ctx.observations:
            date = f"{e.date}: " if e.date else ""
            lines.append(f"    - {date}{e.notes or ''}")

    if ctx.photos and ctx.photos.count > 0:
        last = f", última foto: {ctx.photos.last_taken}" if ctx.photos.last_taken else ""
        lines.append(f"  Fotos: {ctx.photos.count} en total{last}")

    return "\n".join(lines)
