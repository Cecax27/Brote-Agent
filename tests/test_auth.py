from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.tokens import AuthError
from app.config.settings import Settings
from app.main import create_app


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        gemini_api_key="test-key",
        supabase_url="https://test.supabase.co",
        supabase_anon_key="test-anon-key",
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
async def test_chat_malformed_auth_header_returns_401(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": "test-token-without-bearer"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_invalid_token_returns_401(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/chat",
        json={"message": "Hola"},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_chat_valid_token_proceeds(
    auth_client: AsyncClient,
) -> None:
    with pytest.MonkeyPatch.context() as mp:
        async_mock = AsyncMock(return_value={"id": "user-123"})
        mp.setattr("app.auth.dependency.verify_access_token", async_mock)

        client_mock = AsyncMock()
        mp.setattr("app.api.routes.build_user_client", AsyncMock(return_value=client_mock))
        mp.setattr(
            "app.api.routes.build_plant_context",
            AsyncMock(return_value=__import__("app.supabase.context", fromlist=["ContextBundle"]).ContextBundle(light=[])),
        )
        mp.setattr(
            "app.api.routes.call_gemini",
            AsyncMock(return_value={"reply": "Hola"}),
        )

        response = await auth_client.post(
            "/chat",
            json={"message": "Hola"},
            headers={"Authorization": "Bearer test-valid-token"},
        )

    assert response.status_code == 200
