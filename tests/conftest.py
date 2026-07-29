import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        gemini_api_key="test-key",
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon-key",
        action_signing_secret="test-signing-secret",  # noqa: S106
    )


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": "Bearer test-valid-token"}


@pytest.fixture
def app(settings: Settings):
    test_app = create_app()
    test_app.state.settings = settings
    return test_app


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def sync_client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_gemini():
    patcher = patch("app.api.routes.call_gemini", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_auth_verify():
    patcher = patch("app.auth.dependency.verify_access_token", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_context():
    patcher = patch("app.api.routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client():
    patcher = patch("app.api.routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client_actions():
    patcher = patch("app.actions.routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


def _mock_conv() -> MagicMock:
    dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
    conv = MagicMock()
    conv.conversation_id = "conv-test-123"
    conv.user_id = "test-user-id"
    conv.plant_id = None
    conv.title = "Conversación con Flora"
    conv.created_at = dt
    conv.updated_at = dt
    return conv


@pytest.fixture
def mock_conversation_store() -> dict[str, AsyncMock]:
    """Mock all conversation store functions used by the /chat handler."""
    patchers: dict[str, MagicMock] = {}
    mocks: dict[str, AsyncMock] = {}
    targets = [
        "create_conversation",
        "get_conversation",
        "append_message",
        "fetch_history",
        "bump_updated_at",
        "set_title",
        "set_plant_id_once",
    ]
    for name in targets:
        patcher = patch(f"app.api.routes.{name}", new_callable=AsyncMock)
        mocks[name] = patcher.start()
        patchers[name] = patcher

    mocks["create_conversation"].return_value = _mock_conv()
    mocks["get_conversation"].return_value = _mock_conv()
    mocks["fetch_history"].return_value = []

    yield mocks

    for patcher in patchers.values():
        patcher.stop()
