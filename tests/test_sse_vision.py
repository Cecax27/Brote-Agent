from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_data: dict = {"event": "", "data": {}}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_data["event"] = line[7:]
            elif line.startswith("data: "):
                import json

                event_data["data"] = json.loads(line[6:])
        if event_data["event"]:
            events.append(event_data)
    return events


@pytest.fixture
def mock_vision_gemini():
    patcher = patch("app.vision.routes.analyze_image_with_gemini", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_vision_auth():
    patcher = patch("app.auth.dependency.verify_access_token", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_vision_supabase_client():
    patcher = patch("app.vision.routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_vision_context():
    patcher = patch("app.vision.routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_vision_audit():
    patcher = patch("app.vision.routes.log_vision_call")
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_vision_images():
    patchers = {}
    for name in ("validate_image_bytes", "sniff_allowed_mime", "resize_image"):
        patcher = patch(f"app.vision.routes.{name}")
        mock = patcher.start()
        patchers[name] = (patcher, mock)

    patchers["resize_image"][1].return_value = b"resized"
    patchers["sniff_allowed_mime"][1].return_value = "image/jpeg"

    yield patchers

    for patcher, _ in patchers.values():
        patcher.stop()


class TestVisionSSE:
    @pytest.mark.asyncio
    async def test_analyze_upload_sse_emits_status_events(
        self,
        client: AsyncClient,
        mock_vision_gemini: AsyncMock,
        mock_vision_auth: AsyncMock,
        mock_vision_supabase_client: AsyncMock,
        mock_vision_context: AsyncMock,
        mock_vision_audit,
        mock_vision_images,
        auth_headers: dict,
    ) -> None:
        mock_vision_auth.return_value = {"id": "test-user-id"}
        mock_vision_gemini.return_value = {
            "reply": "Tu planta está bien",
            "vision": {},
        }

        response = await client.post(
            "/vision/analyze-upload",
            data={"message": "¿Qué ves?"},
            files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
            headers={
                **auth_headers,
                "Accept": "text/event-stream",
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = _parse_sse(response.text)
        event_types = [e["event"] for e in events]
        assert "status" in event_types
        assert "result" in event_types

        status_steps = [e["data"]["step"] for e in events if e["event"] == "status"]
        assert "analyzing_photo" in status_steps

    @pytest.mark.asyncio
    async def test_analyze_upload_without_accept_returns_json(
        self,
        client: AsyncClient,
        mock_vision_gemini: AsyncMock,
        mock_vision_auth: AsyncMock,
        mock_vision_supabase_client: AsyncMock,
        mock_vision_context: AsyncMock,
        mock_vision_audit,
        mock_vision_images,
        auth_headers: dict,
    ) -> None:
        mock_vision_auth.return_value = {"id": "test-user-id"}
        mock_vision_gemini.return_value = {
            "reply": "Tu planta está bien",
            "vision": {},
        }

        response = await client.post(
            "/vision/analyze-upload",
            data={"message": "¿Qué ves?"},
            files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Tu planta está bien"

    @pytest.mark.asyncio
    async def test_vision_sse_result_event_contains_reply(
        self,
        client: AsyncClient,
        mock_vision_gemini: AsyncMock,
        mock_vision_auth: AsyncMock,
        mock_vision_supabase_client: AsyncMock,
        mock_vision_context: AsyncMock,
        mock_vision_audit,
        mock_vision_images,
        auth_headers: dict,
    ) -> None:
        mock_vision_auth.return_value = {"id": "test-user-id"}
        mock_vision_gemini.return_value = {
            "reply": "Veo una Monstera hermosa",
            "vision": {},
        }

        response = await client.post(
            "/vision/analyze-upload",
            data={"message": "¿Qué ves?"},
            files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
            headers={
                **auth_headers,
                "Accept": "text/event-stream",
            },
        )

        events = _parse_sse(response.text)
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["reply"] == "Veo una Monstera hermosa"
        assert "vision" in result["data"]

    @pytest.mark.asyncio
    async def test_vision_sse_error_on_upstream_failure(
        self,
        client: AsyncClient,
        mock_vision_gemini: AsyncMock,
        mock_vision_auth: AsyncMock,
        mock_vision_supabase_client: AsyncMock,
        mock_vision_context: AsyncMock,
        mock_vision_audit,
        mock_vision_images,
        auth_headers: dict,
    ) -> None:
        from app.vision.core import UpstreamError

        mock_vision_auth.return_value = {"id": "test-user-id"}
        mock_vision_gemini.side_effect = UpstreamError("fallo")

        response = await client.post(
            "/vision/analyze-upload",
            data={"message": "¿Qué ves?"},
            files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
            headers={
                **auth_headers,
                "Accept": "text/event-stream",
            },
        )

        events = _parse_sse(response.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["error"]["code"] == "UPSTREAM_ERROR"
