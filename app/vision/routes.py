from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.actions.helpers import build_proposed_action
from app.auth.dependency import UserIdentity, get_authenticated_user
from app.logging import get_logger
from app.supabase.client import build_user_client
from app.supabase.context import build_plant_context, format_context_for_gemini
from app.vision.audit import log_vision_call
from app.vision.core import UpstreamError, analyze_image_with_gemini
from app.vision.images import (
    InvalidImageError,
    sniff_allowed_mime,
    validate_image_bytes,
    resize_image,
)
from app.vision.models import (
    VisionAnalyzeRequest,
    VisionAnalyzeResponse,
    VisionAnalysis,
)
from app.vision.retrieval import (
    ImageNotFoundError,
    fetch_photo_bytes,
    resolve_journal_photo,
    resolve_plant_latest_photo,
)

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
router = APIRouter(prefix="/vision")


@router.post("/analyze-stored")
async def analyze_stored(
    body: VisionAnalyzeRequest,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),  # noqa: B008, FAST002
) -> VisionAnalyzeResponse:
    settings: "Settings" = request.app.state.settings
    start = time.monotonic()
    original_bytes = 0
    resized_bytes = 0
    mime_type: str | None = None

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    ref = body.image_ref
    if ref.kind == "journal_entry":
        if not ref.journal_entry_id:
            raise ImageNotFoundError()
        resolved = await resolve_journal_photo(client, ref.journal_entry_id)
        source = "journal_entry"
    elif ref.kind == "plant_latest":
        plant_id = ref.plant_id or body.plant_id
        if not plant_id:
            raise ImageNotFoundError()
        resolved = await resolve_plant_latest_photo(client, plant_id)
        source = "plant_latest"
    else:
        raise InvalidImageError("Referencia de imagen no válida.")

    if resolved is None:
        raise ImageNotFoundError()

    try:
        raw = await fetch_photo_bytes(resolved.url, settings)
        original_bytes = len(raw)

        validate_image_bytes(raw, settings)
        mime_type = sniff_allowed_mime(raw, settings) or "image/jpeg"
        resized = resize_image(raw, settings)
        resized_bytes = len(resized)
    except UpstreamError:
        raise
    except InvalidImageError:
        raise
    except Exception as exc:
        logger.exception("vision_stored_processing_failed")
        raise UpstreamError(
            "La imagen no se pudo procesar. Inténtalo de nuevo en un momento."
        ) from exc

    context_str: str | None = None
    effective_plant_id = body.plant_id or ref.plant_id
    if effective_plant_id:
        bundle = await build_plant_context(
            client,
            effective_plant_id,
            max_plants=settings.context_max_plants,
            max_entries=settings.context_max_recent_entries,
        )
        context_str = format_context_for_gemini(bundle)

    try:
        result = await analyze_image_with_gemini(
            resized,
            body.message,
            settings,
            context_str=context_str,
        )
    except UpstreamError:
        elapsed = int((time.monotonic() - start) * 1000)
        log_vision_call(
            endpoint="analyze-stored",
            source=source,
            plant_id=effective_plant_id,
            user_sub=user.sub,
            mime_type=mime_type,
            original_bytes=original_bytes,
            resized_bytes=resized_bytes,
            max_dimension=settings.vision_max_dimension,
            gemini_model=settings.gemini_vision_model,
            vision_kind=None,
            confidence=None,
            status="upstream_error",
            duration_ms=elapsed,
            proposed_action_type=None,
        )
        raise

    reply = str(result.get("reply", ""))
    vision = _parse_vision_analysis(result.get("vision"))
    proposed_action = build_proposed_action(result, effective_plant_id, user.sub, settings)

    elapsed = int((time.monotonic() - start) * 1000)
    log_vision_call(
        endpoint="analyze-stored",
        source=source,
        plant_id=effective_plant_id,
        user_sub=user.sub,
        mime_type=mime_type,
        original_bytes=original_bytes,
        resized_bytes=resized_bytes,
        max_dimension=settings.vision_max_dimension,
        gemini_model=settings.gemini_vision_model,
        vision_kind=vision.kind,
        confidence=vision.confidence,
        status="ok",
        duration_ms=elapsed,
        proposed_action_type=proposed_action.action_type if proposed_action else None,
    )

    return VisionAnalyzeResponse(reply=reply, vision=vision, proposed_action=proposed_action)


@router.post("/analyze-upload")
async def analyze_upload(
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),  # noqa: B008, FAST002
    image: UploadFile = File(...),  # noqa: B008
    message: str = Form(...),
    plant_id: str | None = Form(default=None),
) -> VisionAnalyzeResponse:
    settings: "Settings" = request.app.state.settings
    start = time.monotonic()

    raw = await image.read()
    original_bytes = len(raw)

    if original_bytes > settings.vision_max_image_bytes:
        raise InvalidImageError("La imagen es demasiado grande.")

    validate_image_bytes(raw, settings)
    mime_type = sniff_allowed_mime(raw, settings) or "image/jpeg"
    resized = resize_image(raw, settings)
    resized_bytes = len(resized)

    context_str: str | None = None
    if plant_id:
        client = await build_user_client(
            settings.supabase_url,
            settings.supabase_anon_key,
            user.access_token,
        )
        bundle = await build_plant_context(
            client,
            plant_id,
            max_plants=settings.context_max_plants,
            max_entries=settings.context_max_recent_entries,
        )
        context_str = format_context_for_gemini(bundle)

    try:
        result = await analyze_image_with_gemini(
            resized,
            message,
            settings,
            context_str=context_str,
        )
    except UpstreamError:
        elapsed = int((time.monotonic() - start) * 1000)
        log_vision_call(
            endpoint="analyze-upload",
            source="inline",
            plant_id=plant_id,
            user_sub=user.sub,
            mime_type=mime_type,
            original_bytes=original_bytes,
            resized_bytes=resized_bytes,
            max_dimension=settings.vision_max_dimension,
            gemini_model=settings.gemini_vision_model,
            vision_kind=None,
            confidence=None,
            status="upstream_error",
            duration_ms=elapsed,
            proposed_action_type=None,
        )
        raise

    reply = str(result.get("reply", ""))
    vision = _parse_vision_analysis(result.get("vision"))
    proposed_action = build_proposed_action(result, plant_id, user.sub, settings)

    elapsed = int((time.monotonic() - start) * 1000)
    log_vision_call(
        endpoint="analyze-upload",
        source="inline",
        plant_id=plant_id,
        user_sub=user.sub,
        mime_type=mime_type,
        original_bytes=original_bytes,
        resized_bytes=resized_bytes,
        max_dimension=settings.vision_max_dimension,
        gemini_model=settings.gemini_vision_model,
        vision_kind=vision.kind,
        confidence=vision.confidence,
        status="ok",
        duration_ms=elapsed,
        proposed_action_type=proposed_action.action_type if proposed_action else None,
    )

    return VisionAnalyzeResponse(reply=reply, vision=vision, proposed_action=proposed_action)


def _parse_vision_analysis(raw: Any) -> VisionAnalysis:
    if isinstance(raw, dict):
        try:
            return VisionAnalysis(**raw)
        except ValidationError:
            pass
    return VisionAnalysis(kind="declined")
