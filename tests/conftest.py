import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

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
