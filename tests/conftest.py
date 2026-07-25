import os
import time
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import jwt

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.supabase.context import ContextBundle


def build_test_token(
    *,
    sub: str = "test-user-id",
    secret: str = "test-jwt-secret",
    audience: str = "authenticated",
    issuer: str = "https://test.supabase.co/auth/v1",
    expired: bool = False,
    bad_secret: bool = False,
) -> str:
    now = int(time.time())
    exp = now - 3600 if expired else now + 3600
    key = "wrong-secret" if bad_secret else secret
    return jwt.encode(
        {"sub": sub, "iss": issuer, "aud": audience, "exp": exp, "iat": now},
        key,
        algorithm="HS256",
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        gemini_api_key="test-key",
        supabase_url="https://test.supabase.co",
        supabase_jwt_secret="test-jwt-secret",
    )


@pytest.fixture
def valid_token() -> str:
    return build_test_token()


@pytest.fixture
def auth_headers(valid_token: str) -> dict:
    return {"Authorization": f"Bearer {valid_token}"}


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
def mock_supabase_context():
    patcher = patch("app.api.routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client():
    patcher = patch("app.api.routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()
