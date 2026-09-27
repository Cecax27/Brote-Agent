"""Unit tests for the auto_vision helper module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.auto_vision import (
    FOLLOWUP_RESPONSE_SCHEMA,
    VisionSubCallMissingPhotoError,
    VisionSubCallUpstreamError,
    format_missing_photo_block,
    format_vision_followup_block,
    parse_internal_vision_request,
    run_auto_vision_followup,
    run_text_only_followup,
)
from app.vision.models import VisionAnalysis, VisionSpeciesCandidate
from app.vision.retrieval import ImageNotFoundError, ResolvedPhoto

# ---------------------------------------------------------------------------
# parse_internal_vision_request
# ---------------------------------------------------------------------------


class TestParseInternalVisionRequest:
    def test_returns_none_when_no_vision_request(self) -> None:
        assert parse_internal_vision_request({"reply": "hi"}, "plant-1") is None

    def test_returns_none_when_vision_request_is_null(self) -> None:
        assert (
            parse_internal_vision_request({"reply": "hi", "vision_request": None}, "plant-1")
            is None
        )

    def test_returns_none_when_vision_request_malformed(self) -> None:
        assert parse_internal_vision_request({"vision_request": "garbage"}, "plant-1") is None

    def test_returns_none_when_kind_unknown(self) -> None:
        assert (
            parse_internal_vision_request(
                {
                    "vision_request": {
                        "reason_es": "x",
                        "suggested_ref": {"kind": "weird"},
                    }
                },
                "plant-1",
            )
            is None
        )

    def test_returns_none_when_journal_entry_id_missing(self) -> None:
        assert (
            parse_internal_vision_request(
                {
                    "vision_request": {
                        "reason_es": "x",
                        "suggested_ref": {"kind": "journal_entry"},
                    }
                },
                "plant-1",
            )
            is None
        )

    def test_returns_none_when_plant_latest_id_missing(self) -> None:
        assert (
            parse_internal_vision_request(
                {
                    "vision_request": {
                        "reason_es": "x",
                        "suggested_ref": {"kind": "plant_latest"},
                    }
                },
                "plant-1",
            )
            is None
        )

    def test_returns_none_on_plant_mismatch(self) -> None:
        assert (
            parse_internal_vision_request(
                {
                    "vision_request": {
                        "reason_es": "x",
                        "suggested_ref": {
                            "kind": "plant_latest",
                            "plant_id": "plant-A",
                        },
                    }
                },
                "plant-B",
            )
            is None
        )

    def test_returns_journal_entry_ref(self) -> None:
        result = parse_internal_vision_request(
            {
                "vision_request": {
                    "reason_es": "porque sí",
                    "suggested_ref": {
                        "kind": "journal_entry",
                        "journal_entry_id": "11111111-2222-3333-4444-555555555555",
                    },
                }
            },
            "plant-1",
        )
        assert result is not None
        assert result["suggested_ref"]["kind"] == "journal_entry"
        assert result["suggested_ref"]["journal_entry_id"] == "11111111-2222-3333-4444-555555555555"

    def test_returns_plant_latest_ref(self) -> None:
        result = parse_internal_vision_request(
            {
                "vision_request": {
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                }
            },
            "plant-abc",
        )
        assert result is not None
        assert result["suggested_ref"]["kind"] == "plant_latest"
        assert result["suggested_ref"]["plant_id"] == "plant-abc"


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


class TestFormatVisionFollowupBlock:
    def test_includes_reason(self) -> None:
        block = format_vision_followup_block(
            {"vision": {"kind": "health", "diagnosis": "Exceso de riego"}},
            "Las manchas importan",
        )
        assert "Las manchas importan" in block
        assert "Exceso de riego" in block

    def test_includes_species_candidates(self) -> None:
        vision = VisionAnalysis(
            kind="identify",
            possible_species=[
                VisionSpeciesCandidate(name="Monstera deliciosa", confidence="alta"),
            ],
        )
        block = format_vision_followup_block(
            {"vision": vision.model_dump()},
            "x",
        )
        assert "Monstera deliciosa" in block

    def test_includes_confidence_and_needs_more_info(self) -> None:
        vision = VisionAnalysis(
            kind="health",
            diagnosis="…",
            confidence="baja",
            needs_more_info={"question_es": "¿Cuánta luz recibe?"},
        )
        block = format_vision_followup_block({"vision": vision.model_dump()}, "x")
        assert "baja" in block
        assert "¿Cuánta luz recibe?" in block

    def test_handles_declined_kind(self) -> None:
        vision = VisionAnalysis(kind="declined")
        block = format_vision_followup_block({"vision": vision.model_dump()}, "x")
        assert "no parece estar relacionada con plantas" in block

    def test_falls_back_to_reply_text_when_vision_missing(self) -> None:
        block = format_vision_followup_block({"reply": "Veo una planta bonita."}, "x")
        assert "Veo una planta bonita." in block


class TestFormatMissingPhotoBlock:
    def test_mentions_photo_unavailable(self) -> None:
        block = format_missing_photo_block("motivo de la foto")
        assert "motivo de la foto" in block
        assert "no está disponible" in block
        assert "sin inventar un diagnóstico" in block


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


class TestFollowupSchema:
    def test_has_no_vision_request_field(self) -> None:
        props = FOLLOWUP_RESPONSE_SCHEMA.get("properties", {})
        assert "vision_request" not in props
        assert "vision" not in props
        assert "reply" in props

    def test_required_keys(self) -> None:
        assert "reply" in FOLLOWUP_RESPONSE_SCHEMA.get("required", [])


# ---------------------------------------------------------------------------
# Auto-vision subcall: photo resolution + Gemini call
# ---------------------------------------------------------------------------


class TestRunAutoVisionFollowup:
    @pytest.mark.asyncio
    async def test_calls_vision_then_gemini(self) -> None:
        fake_client = AsyncMock()
        settings = AsyncMock()
        settings.gemini_api_key = "k"
        settings.gemini_model = "m"
        settings.gemini_temperature = 0.7
        settings.gemini_max_output_tokens = 1024

        with (
            patch(
                "app.agent.auto_vision.resolve_plant_latest_photo",
                new_callable=AsyncMock,
            ) as mock_resolve,
            patch(
                "app.agent.auto_vision.fetch_photo_bytes",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch("app.agent.auto_vision.validate_image_bytes") as mock_validate,
            patch(
                "app.agent.auto_vision.sniff_allowed_mime",
                return_value="image/jpeg",
            ),
            patch("app.agent.auto_vision.resize_image", return_value=b"resized"),
            patch(
                "app.agent.auto_vision.analyze_image_with_gemini",
                new_callable=AsyncMock,
            ) as mock_vision,
            patch("app.agent.auto_vision.call_gemini", new_callable=AsyncMock) as mock_call,
        ):
            from app.vision.retrieval import ResolvedPhoto

            mock_resolve.return_value = ResolvedPhoto(url="https://x/y.jpg")
            mock_fetch.return_value = b"raw"
            mock_vision.return_value = {
                "reply": "v",
                "vision": {"kind": "health", "diagnosis": "d"},
            }
            mock_call.return_value = {"reply": "final"}

            result = await run_auto_vision_followup(
                client=fake_client,
                vision_request={
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                effective_plant_id="plant-abc",
                body_message="m",
                base_context_str="ctx",
                settings=settings,
            )

        assert result == {"reply": "final"}
        mock_vision.assert_called_once()
        mock_call.assert_called_once()
        # The second Gemini call sees the vision summary in its context.
        call_kwargs = mock_call.call_args.kwargs
        assert "Análisis visual automático" in call_kwargs["context"]
        assert "Exceso" in call_kwargs["context"] or "d" in call_kwargs["context"]

    @pytest.mark.asyncio
    async def test_missing_photo_raises_missing_error(self) -> None:
        fake_client = AsyncMock()
        settings = AsyncMock()
        with (
            patch(
                "app.agent.auto_vision.resolve_plant_latest_photo",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(VisionSubCallMissingPhotoError),
        ):
            await run_auto_vision_followup(
                client=fake_client,
                vision_request={
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                effective_plant_id="plant-abc",
                body_message="m",
                base_context_str=None,
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_invalid_image_raises_missing_error(self) -> None:
        fake_client = AsyncMock()
        settings = AsyncMock()
        from app.vision.images import InvalidImageError

        with (
            patch(
                "app.agent.auto_vision.resolve_plant_latest_photo",
                new_callable=AsyncMock,
                return_value=ResolvedPhoto(url="https://x/y.jpg"),
            ),
            patch(
                "app.agent.auto_vision.fetch_photo_bytes",
                new_callable=AsyncMock,
                return_value=b"raw",
            ),
            patch(
                "app.agent.auto_vision.validate_image_bytes",
                side_effect=InvalidImageError("bad"),
            ),
            pytest.raises(VisionSubCallMissingPhotoError),
        ):
            await run_auto_vision_followup(
                client=fake_client,
                vision_request={
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                effective_plant_id="plant-abc",
                body_message="m",
                base_context_str=None,
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_vision_gemini_failure_raises_upstream_error(self) -> None:
        from app.agent.loop import UpstreamError

        fake_client = AsyncMock()
        settings = AsyncMock()
        settings.gemini_api_key = "k"
        settings.gemini_model = "m"
        settings.gemini_temperature = 0.7
        settings.gemini_max_output_tokens = 1024

        with (
            patch(
                "app.agent.auto_vision.resolve_plant_latest_photo",
                new_callable=AsyncMock,
                return_value=ResolvedPhoto(url="https://x/y.jpg"),
            ),
            patch(
                "app.agent.auto_vision.fetch_photo_bytes",
                new_callable=AsyncMock,
                return_value=b"raw",
            ),
            patch("app.agent.auto_vision.validate_image_bytes"),
            patch(
                "app.agent.auto_vision.sniff_allowed_mime",
                return_value="image/jpeg",
            ),
            patch("app.agent.auto_vision.resize_image", return_value=b"resized"),
            patch(
                "app.agent.auto_vision.analyze_image_with_gemini",
                new_callable=AsyncMock,
                side_effect=UpstreamError("vision 502"),
            ),
            pytest.raises(VisionSubCallUpstreamError),
        ):
            await run_auto_vision_followup(
                client=fake_client,
                vision_request={
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                effective_plant_id="plant-abc",
                body_message="m",
                base_context_str="ctx",
                settings=settings,
            )


# ---------------------------------------------------------------------------
# run_text_only_followup
# ---------------------------------------------------------------------------


class TestRunTextOnlyFollowup:
    @pytest.mark.asyncio
    async def test_calls_gemini_with_missing_photo_block(self) -> None:
        settings = AsyncMock()
        settings.gemini_api_key = "k"
        settings.gemini_model = "m"
        settings.gemini_temperature = 0.7
        settings.gemini_max_output_tokens = 1024

        with patch(
            "app.agent.auto_vision.call_gemini",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = {"reply": "text-only reply"}

            result = await run_text_only_followup(
                body_message="m",
                base_context_str="ctx",
                vision_request={
                    "reason_es": "motivo",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                settings=settings,
            )

        assert result == {"reply": "text-only reply"}
        call_kwargs = mock_call.call_args.kwargs
        assert "no está disponible" in call_kwargs["context"]
        assert "motivo" in call_kwargs["context"]

    @pytest.mark.asyncio
    async def test_upstream_failure_raises_upstream_error(self) -> None:
        from app.agent.loop import UpstreamError

        settings = AsyncMock()
        settings.gemini_api_key = "k"
        settings.gemini_model = "m"
        settings.gemini_temperature = 0.7
        settings.gemini_max_output_tokens = 1024

        with (
            patch(
                "app.agent.auto_vision.call_gemini",
                new_callable=AsyncMock,
                side_effect=UpstreamError("text-only 502"),
            ),
            pytest.raises(VisionSubCallUpstreamError),
        ):
            await run_text_only_followup(
                body_message="m",
                base_context_str=None,
                vision_request={
                    "reason_es": "x",
                    "suggested_ref": {
                        "kind": "plant_latest",
                        "plant_id": "plant-abc",
                    },
                },
                settings=settings,
            )


# Silence unused-import warnings while keeping `ImageNotFoundError` import for
# completeness (other test files in this suite exercise the live path).
_ = ImageNotFoundError
