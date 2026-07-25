import time

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.config.settings import Settings
from app.main import create_app


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
def test_secret() -> str:
    return "test-jwt-secret"


@pytest.fixture
def valid_token(test_secret: str) -> str:
    return build_test_token(secret=test_secret)


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        gemini_api_key="test-key",
        supabase_url="https://test.supabase.co",
        supabase_jwt_secret="test-jwt-secret",
    )


@pytest.fixture
def auth_app(auth_settings: Settings):
    app = create_app()
    app.state.settings = auth_settings
    return app


@pytest.fixture
async def auth_client(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_chat_missing_auth_header_returns_401(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/chat", json={"message": "Hola"})
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "sesión" in data["error"]["message"]


@pytest.mark.asyncio
async def test_chat_malformed_token_returns_401(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": "not-a-valid-jwt"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_chat_expired_token_returns_401(
    auth_client: AsyncClient, test_secret: str
) -> None:
    token = build_test_token(secret=test_secret, expired=True)
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_chat_bad_signature_returns_401(
    auth_client: AsyncClient, test_secret: str
) -> None:
    token = build_test_token(secret=test_secret, bad_secret=True)
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_chat_malformed_auth_header_returns_401(
    auth_client: AsyncClient, valid_token: str
) -> None:
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": valid_token},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_valid_token_proceeds(
    auth_client: AsyncClient, valid_token: str
) -> None:
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code != 401
