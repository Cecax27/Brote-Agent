import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key="test-key")  # type: ignore[call-arg]


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
def mock_openai():
    patcher = patch("app.api.routes.call_openai", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()
