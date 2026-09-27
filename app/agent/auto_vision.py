"""Inline auto-vision sub-call inside a chat turn.

When the agent decides it needs to see a photo, the chat stream resolves
the referenced image, runs a vision analysis on the server, then asks the
agent to compose a final reply informed by the visual diagnosis.

This module encapsulates the resolution + analysis + second-call flow so
both the streaming (`/chat/stream`) and single-shot (`/chat`) handlers can
share the same logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.agent.loop import UpstreamError, call_gemini
from app.logging import get_logger
from app.vision.core import analyze_image_with_gemini
from app.vision.images import (
    InvalidImageError,
    resize_image,
    sniff_allowed_mime,
    validate_image_bytes,
)
from app.vision.models import VisionAnalysis
from app.vision.retrieval import (
    ImageNotFoundError,
    fetch_photo_bytes,
    resolve_journal_photo,
    resolve_plant_latest_photo,
)

if TYPE_CHECKING:
    from supabase._async.client import AsyncClient

    from app.config.settings import Settings


logger = get_logger(__name__)


def _build_followup_schema() -> dict[str, Any]:
    """Schema for the second-pass Gemini call.

    Smaller than ACTION_RESPONSE_SCHEMA: no `vision_request` (final turn) and
    no `vision` (already absorbed by the second pass). Mirrors the writable
    surface so the agent can still propose actions on this final reply.
    """
    return {
        "type": "OBJECT",
        "properties": {
            "reply": {"type": "STRING"},
            "proposed_action": {
                "type": "OBJECT",
                "nullable": True,
                "properties": {
                    "action_type": {
                        "type": "STRING",
                        "enum": ["create_watering_schedule", "add_journal_entry"],
                    },
                    "plant_id": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "summary_es": {"type": "STRING"},
                    "payload": {
                        "type": "OBJECT",
                        "properties": {
                            "frequency_days": {"type": "NUMBER"},
                            "next_due_at": {"type": "STRING"},
                            "last_watered_at": {"type": "STRING"},
                            "notify_time": {"type": "STRING"},
                            "content": {"type": "STRING"},
                        },
                    },
                },
                "required": ["action_type", "plant_id", "title", "summary_es", "payload"],
            },
        },
        "required": ["reply"],
    }


FOLLOWUP_RESPONSE_SCHEMA: dict[str, Any] = _build_followup_schema()


class VisionSubCallMissingPhotoError(Exception):
    """Photo couldn't be retrieved (missing, invalid, RLS denial, oversized).

    Recoverable: caller should retry with a text-only follow-up that tells
    the agent the photo is unavailable.
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class VisionSubCallUpstreamError(Exception):
    """Vision Gemini call failed, or Storage fetch returned an upstream error.

    Not recoverable on this turn: caller should stop with an
    `UPSTREAM_ERROR` and surface the message to the user.
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


def parse_internal_vision_request(  # noqa: PLR0911
    result: dict[str, Any],
    effective_plant_id: str | None,
) -> dict[str, Any] | None:
    """Extract the `vision_request` payload from the agent's first-pass reply.

    Returns the raw dict (reason_es + suggested_ref) so the caller can route
    the resolution + analysis. Returns None if no vision is requested or the
    payload is malformed.
    """
    raw = result.get("vision_request")
    if raw is None or not isinstance(raw, dict):
        return None

    suggested_raw = raw.get("suggested_ref")
    if not isinstance(suggested_raw, dict):
        return None

    kind = str(suggested_raw.get("kind", ""))
    if kind not in ("journal_entry", "plant_latest"):
        return None

    if kind == "journal_entry":
        journal_entry_id = str(suggested_raw.get("journal_entry_id", "") or "")
        if not journal_entry_id:
            return None
    else:
        ref_plant_id = str(suggested_raw.get("plant_id", "") or "")
        if not ref_plant_id:
            return None
        if effective_plant_id is not None and ref_plant_id != effective_plant_id:
            logger.warning(
                "internal_vision_request_plant_mismatch",
                vision_plant=ref_plant_id,
                request_plant=effective_plant_id,
            )
            return None

    return raw


async def _resolve_photo_bytes(
    client: "AsyncClient",
    suggested_ref: dict[str, Any],
    fallback_plant_id: str | None,
    settings: "Settings",
) -> bytes:
    """Resolve and download the referenced photo. Raises on failure."""
    kind = str(suggested_ref.get("kind", ""))
    if kind == "journal_entry":
        journal_entry_id = str(suggested_ref.get("journal_entry_id", "") or "")
        resolved = await resolve_journal_photo(client, journal_entry_id)
    else:
        ref_plant_id = str(suggested_ref.get("plant_id", "") or "") or (fallback_plant_id or "")
        if not ref_plant_id:
            raise ImageNotFoundError
        resolved = await resolve_plant_latest_photo(client, ref_plant_id)

    if resolved is None:
        raise ImageNotFoundError

    raw = await fetch_photo_bytes(resolved.url, settings)
    validate_image_bytes(raw, settings)
    sniff_allowed_mime(raw, settings)  # validates; result discarded here
    return resize_image(raw, settings)


async def _run_vision_subcall(  # noqa: PLR0913, PLR0917
    client: "AsyncClient",
    suggested_ref: dict[str, Any],
    fallback_plant_id: str | None,
    body_message: str,
    context_str: str | None,
    settings: "Settings",
) -> dict[str, Any]:
    """Resolve photo, run vision Gemini, return the parsed vision_result dict.

    Raises:
        VisionSubCallMissingPhotoError: photo unavailable (missing/invalid).
        VisionSubCallUpstreamError: Storage download or vision Gemini failure.
    """
    try:
        resized = await _resolve_photo_bytes(
            client,
            suggested_ref,
            fallback_plant_id,
            settings,
        )
    except ImageNotFoundError:
        _missing_message = "Imagen no encontrada."
        raise VisionSubCallMissingPhotoError(_missing_message) from None
    except InvalidImageError as exc:
        raise VisionSubCallMissingPhotoError(str(exc)) from exc
    except UpstreamError as exc:
        # Storage download failure — treat as upstream error (service problem).
        raise VisionSubCallUpstreamError(str(exc)) from exc
    except Exception as exc:
        logger.exception("auto_vision_resolve_failed")
        _processing_message = "La imagen no se pudo procesar. Inténtalo de nuevo en un momento."
        raise VisionSubCallUpstreamError(_processing_message) from exc

    try:
        return await analyze_image_with_gemini(
            resized,
            body_message,
            settings,
            context_str=context_str,
        )
    except UpstreamError as exc:
        raise VisionSubCallUpstreamError(str(exc)) from exc


def format_vision_followup_block(vision_result: dict[str, Any], reason_es: str) -> str:
    """Build the 'I just looked at the photo' block for the second Gemini call.

    The block is short, structured, and human-readable so the second-pass
    model can absorb the diagnosis into its final reply.
    """
    lines = ["[Análisis visual automático de Flora]", f"Motivo: {reason_es}"]

    vision_raw = vision_result.get("vision")
    if isinstance(vision_raw, dict):
        try:
            vision = VisionAnalysis(**vision_raw)
        except Exception:  # noqa: BLE001
            vision = None
    else:
        vision = None

    if vision is not None:
        if vision.kind == "declined":
            lines.append("Resultado: la imagen no parece estar relacionada con plantas.")
        else:
            if vision.diagnosis:
                lines.append(f"Diagnóstico: {vision.diagnosis}")
            if vision.possible_species:
                candidates = ", ".join(
                    f"{c.name} ({c.confidence})" for c in vision.possible_species
                )
                lines.append(f"Especies posibles: {candidates}")
            if vision.confidence:
                lines.append(f"Confianza: {vision.confidence}")
            if vision.needs_more_info and vision.needs_more_info.question_es:
                lines.append(f"Pregunta pendiente: {vision.needs_more_info.question_es}")
    else:
        reply_text = str(vision_result.get("reply", "")).strip()
        if reply_text:
            lines.append(f"Observaciones: {reply_text}")

    return "\n".join(lines)


def format_missing_photo_block(reason_es: str) -> str:
    """Build a follow-up block when the referenced photo could not be retrieved.

    The second-pass call uses this to compose a text-only reply without the
    vision diagnosis.
    """
    return (
        "[Análisis visual automático de Flora]\n"
        f"Motivo: {reason_es}\n"
        "Resultado: la foto que querías ver no está disponible (puede que el "
        "usuario no haya subido ninguna o que ya no esté accesible). Responde "
        "solo con el contexto que tengas, sin inventar un diagnóstico visual."
    )


async def run_auto_vision_followup(  # noqa: PLR0913
    *,
    client: "AsyncClient",
    vision_request: dict[str, Any],
    effective_plant_id: str | None,
    body_message: str,
    base_context_str: str | None,
    settings: "Settings",
) -> dict[str, Any]:
    """Resolve, analyze, and run the second Gemini call.

    Returns the second-pass result dict (always a dict with at least a
    `reply` key — same shape as the first-pass Gemini result so callers can
    reuse `build_proposed_action`).

    Raises:
        VisionSubCallMissingPhotoError: photo unavailable (caller should
            retry with text-only follow-up).
        VisionSubCallUpstreamError: Storage or vision Gemini failure
            (caller should stop with UPSTREAM_ERROR).
    """
    suggested_ref_raw = vision_request.get("suggested_ref") or {}
    reason_es = str(vision_request.get("reason_es", "")).strip()

    vision_result = await _run_vision_subcall(
        client,
        suggested_ref_raw,
        effective_plant_id,
        body_message,
        base_context_str,
        settings,
    )

    followup_block = format_vision_followup_block(vision_result, reason_es)
    followup_context = (
        f"{base_context_str}\n\n{followup_block}" if base_context_str else followup_block
    )

    try:
        return await call_gemini(
            message=body_message,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_output_tokens,
            context=followup_context,
            response_schema=FOLLOWUP_RESPONSE_SCHEMA,
        )
    except UpstreamError as exc:
        raise VisionSubCallUpstreamError(str(exc)) from exc


async def run_text_only_followup(
    *,
    body_message: str,
    base_context_str: str | None,
    vision_request: dict[str, Any],
    settings: "Settings",
) -> dict[str, Any]:
    """Second Gemini call when the photo couldn't be retrieved.

    The agent gets a 'photo unavailable' note and composes a text-only
    reply from context.

    Raises:
        VisionSubCallUpstreamError: the second Gemini call failed.
    """
    reason_es = str(vision_request.get("reason_es", "")).strip()
    followup_block = format_missing_photo_block(reason_es)
    followup_context = (
        f"{base_context_str}\n\n{followup_block}" if base_context_str else followup_block
    )

    try:
        return await call_gemini(
            message=body_message,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_output_tokens,
            context=followup_context,
            response_schema=FOLLOWUP_RESPONSE_SCHEMA,
        )
    except UpstreamError as exc:
        raise VisionSubCallUpstreamError(str(exc)) from exc
