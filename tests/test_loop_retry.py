"""Tests for the JSON-parse retry logic in app/agent/loop.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.loop import UpstreamError, call_gemini


@pytest.fixture
def mock_generate():
    """Patch the underlying genai client call."""
    patcher = patch("app.agent.loop._generate_once", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_logger():
    patcher = patch("app.agent.loop.logger")
    yield patcher.start()
    patcher.stop()


class TestCallGeminiHappyPath:
    @pytest.mark.asyncio
    async def test_valid_json_no_retry(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        mock_generate.return_value = json.dumps({"reply": "Hola"})

        result = await call_gemini(
            message="user msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        assert result == {"reply": "Hola"}
        assert mock_generate.call_count == 1
        warning_events = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert "gemini_json_parse_failed_preview" not in warning_events


class TestCallGeminiRetry:
    @pytest.mark.asyncio
    async def test_retries_on_json_decode_error(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        # First call: truncated JSON mid-string. Second call: valid.
        bad = '{"reply": "incompleta'
        good = json.dumps({"reply": "Final reply"})
        mock_generate.side_effect = [bad, good]

        result = await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        assert result == {"reply": "Final reply"}
        assert mock_generate.call_count == 2

    @pytest.mark.asyncio
    async def test_first_retry_uses_doubled_max_output_tokens(
        self, mock_generate: AsyncMock
    ) -> None:
        bad = '{"reply": "cut'
        good = json.dumps({"reply": "ok"})
        mock_generate.side_effect = [bad, good]

        await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        assert mock_generate.call_count == 2
        # The second call sees max_output_tokens=2048 in config_kwargs.
        second_kwargs = mock_generate.call_args_list[1].kwargs["config_kwargs"]
        assert second_kwargs["max_output_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_second_retry_uses_quadrupled_max_output_tokens(
        self, mock_generate: AsyncMock
    ) -> None:
        bad = '{"reply": "cut'
        bad_again = '{"reply": "still cut'
        good = json.dumps({"reply": "ok after escalation"})
        mock_generate.side_effect = [bad, bad_again, good]

        result = await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        assert result == {"reply": "ok after escalation"}
        assert mock_generate.call_count == 3
        # Second retry sees max_output_tokens=4096 in config_kwargs.
        third_kwargs = mock_generate.call_args_list[2].kwargs["config_kwargs"]
        assert third_kwargs["max_output_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_retry_logs_preview_with_truncated_content(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        bad = '{"reply": "' + ("x" * 1000)
        good = json.dumps({"reply": "ok"})
        mock_generate.side_effect = [bad, good]

        await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        preview_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if call.args and call.args[0] == "gemini_json_parse_failed_preview"
        ]
        assert len(preview_calls) == 1
        preview_value = preview_calls[0].kwargs["content_preview"]
        # Preview is truncated to 500 chars.
        assert len(preview_value) == 500
        # Actual content length is logged in full.
        assert preview_calls[0].kwargs["content_length"] == len(bad)
        # First-retry budget is announced in the same log line.
        assert preview_calls[0].kwargs["retry_max_output_tokens"] == 2048
        assert preview_calls[0].kwargs["attempt"] == 1

    @pytest.mark.asyncio
    async def test_logs_response_length_when_first_retry_also_fails(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        bad = '{"reply": "' + ("a" * 800)
        bad_again = '{"reply": "' + ("b" * 1500)
        good = json.dumps({"reply": "ok after escalation"})
        mock_generate.side_effect = [bad, bad_again, good]

        await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        preview_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if call.args and call.args[0] == "gemini_json_parse_failed_preview"
        ]
        # Two preview warnings: one for the first failure, one for the second.
        assert len(preview_calls) == 2
        assert preview_calls[0].kwargs["attempt"] == 1
        assert preview_calls[0].kwargs["retry_max_output_tokens"] == 2048
        assert preview_calls[1].kwargs["attempt"] == 2
        assert preview_calls[1].kwargs["retry_max_output_tokens"] == 4096
        # Each preview records the length of its OWN failing content.
        assert preview_calls[0].kwargs["content_length"] == len(bad)
        assert preview_calls[1].kwargs["content_length"] == len(bad_again)

    @pytest.mark.asyncio
    async def test_retry_logs_done_event(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        bad = '{"reply": "cut'
        good = json.dumps({"reply": "ok"})
        mock_generate.side_effect = [bad, good]

        await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
            response_schema={"type": "OBJECT"},
        )

        info_events = [call.args[0] for call in mock_logger.info.call_args_list]
        assert "gemini_call_done_after_retry" in info_events

    @pytest.mark.asyncio
    async def test_all_three_calls_fail_raises_upstream(
        self, mock_generate: AsyncMock, mock_logger: MagicMock
    ) -> None:
        bad = '{"reply": "cut'
        bad_again = '{"reply": "still cut'
        bad_third = '{"reply": "still cut again'
        mock_generate.side_effect = [bad, bad_again, bad_third]

        with pytest.raises(UpstreamError):
            await call_gemini(
                message="msg",
                api_key="k",
                model="m",
                temperature=0.7,
                max_output_tokens=1024,
                response_schema={"type": "OBJECT"},
            )

        assert mock_generate.call_count == 3
        error_events = [call.args[0] for call in mock_logger.error.call_args_list]
        assert "gemini_json_parse_failed_after_retry" in error_events


class TestCallGeminiNoRetryOnUpstreamError:
    @pytest.mark.asyncio
    async def test_upstream_error_first_call_propagates_no_retry(
        self, mock_generate: AsyncMock
    ) -> None:
        mock_generate.side_effect = RuntimeError("Gemini 5xx")

        with pytest.raises(UpstreamError):
            await call_gemini(
                message="msg",
                api_key="k",
                model="m",
                temperature=0.7,
                max_output_tokens=1024,
                response_schema={"type": "OBJECT"},
            )

        assert mock_generate.call_count == 1

    @pytest.mark.asyncio
    async def test_upstream_error_on_first_retry_propagates(self, mock_generate: AsyncMock) -> None:
        mock_generate.side_effect = [
            '{"reply": "cut',
            RuntimeError("Gemini 5xx on first retry"),
        ]

        with pytest.raises(UpstreamError):
            await call_gemini(
                message="msg",
                api_key="k",
                model="m",
                temperature=0.7,
                max_output_tokens=1024,
                response_schema={"type": "OBJECT"},
            )

        assert mock_generate.call_count == 2

    @pytest.mark.asyncio
    async def test_upstream_error_on_second_retry_propagates(
        self, mock_generate: AsyncMock
    ) -> None:
        mock_generate.side_effect = [
            '{"reply": "cut',
            '{"reply": "still cut',
            RuntimeError("Gemini 5xx on second retry"),
        ]

        with pytest.raises(UpstreamError):
            await call_gemini(
                message="msg",
                api_key="k",
                model="m",
                temperature=0.7,
                max_output_tokens=1024,
                response_schema={"type": "OBJECT"},
            )

        assert mock_generate.call_count == 3


class TestCallGeminiTextModeNoRetry:
    @pytest.mark.asyncio
    async def test_text_mode_does_not_retry_on_bad_text(self, mock_generate: AsyncMock) -> None:
        # No response_schema → text mode. Bad text should NOT trigger retry.
        mock_generate.return_value = "not json, that's fine"

        result = await call_gemini(
            message="msg",
            api_key="k",
            model="m",
            temperature=0.7,
            max_output_tokens=1024,
        )

        assert result == "not json, that's fine"
        assert mock_generate.call_count == 1

    @pytest.mark.asyncio
    async def test_non_dict_parsed_raises_upstream(self, mock_generate: AsyncMock) -> None:
        mock_generate.return_value = json.dumps(["a", "list", "not", "a", "dict"])

        with pytest.raises(UpstreamError):
            await call_gemini(
                message="msg",
                api_key="k",
                model="m",
                temperature=0.7,
                max_output_tokens=1024,
                response_schema={"type": "OBJECT"},
            )

        assert mock_generate.call_count == 1
