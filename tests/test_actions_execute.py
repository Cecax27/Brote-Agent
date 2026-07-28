from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.actions.tokens import _nonce_store, issue_confirm_token

SIGNING_SECRET = "test-signing-secret"


def _make_token(action_type: str, plant_id: str, payload: dict, sub: str) -> str:
    return issue_confirm_token(action_type, plant_id, payload, sub, SIGNING_SECRET, 600)


@pytest.fixture(autouse=True)
def _clear_nonce_store() -> None:
    _nonce_store.clear()
    yield
    _nonce_store.clear()


@pytest.fixture
def mock_execute_handlers() -> AsyncMock:
    patcher = patch("app.actions.handlers.create_watering_schedule", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_journal_handler() -> AsyncMock:
    patcher = patch("app.actions.handlers.add_journal_entry", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


class TestExecuteAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "p1",
                "payload": {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"},
                "confirm_token": "any",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_token_returns_401(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.side_effect = __import__(
            "app.auth.tokens", fromlist=["AuthError"]
        ).AuthError("bad")
        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "p1",
                "payload": {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"},
                "confirm_token": "any",
            },
            headers=auth_headers,
        )
        assert response.status_code == 401


class TestExecuteHappyPath:
    @pytest.mark.asyncio
    async def test_create_watering_schedule_returns_201(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,  # noqa: ARG002
        mock_execute_handlers: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_execute_handlers.return_value = "schedule-id-123"

        payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token("create_watering_schedule", "plant-123", payload, "test-user-id")

        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "plant-123",
                "payload": payload,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["action_id"] == "schedule-id-123"
        assert data["action_type"] == "create_watering_schedule"
        assert data["status"] == "executed"
        mock_execute_handlers.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_journal_entry_returns_201(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        mock_journal_handler: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_journal_handler.return_value = "journal-id-456"

        payload = {"content": "Regar cada 7 días"}
        token = _make_token("add_journal_entry", "plant-123", payload, "test-user-id")

        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "add_journal_entry",
                "plant_id": "plant-123",
                "payload": payload,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["action_id"] == "journal-id-456"
        mock_journal_handler.assert_called_once()


class TestExecuteTokenLifecycle:
    @pytest.mark.asyncio
    async def test_expired_token_returns_401(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token("create_watering_schedule", "p1", payload, "test-user-id")
        _nonce_store.clear()

        import time

        time.sleep(0.01)
        with patch("app.actions.tokens.time.time", return_value=time.time() + 601):
            response = await client.post(
                "/actions/execute",
                json={
                    "action_type": "create_watering_schedule",
                    "plant_id": "p1",
                    "payload": payload,
                    "confirm_token": token,
                },
                headers=auth_headers,
            )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_user_token_returns_401(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        auth_headers: dict,
    ) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token("create_watering_schedule", "p1", payload, "user-A")
        mock_auth_verify.return_value = {"id": "user-B"}

        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "p1",
                "payload": payload,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_altered_payload_returns_401(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        original_payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token(
            "create_watering_schedule", "plant-123", original_payload, "test-user-id"
        )
        altered = {"frequency_days": 7, "next_due_at": "2025-06-09T00:00:00Z"}

        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "plant-123",
                "payload": altered,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        assert response.status_code == 401


class TestExecuteAllowlist:
    @pytest.mark.asyncio
    async def test_unsupported_action_type_returns_400(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "delete_plant",
                "plant_id": "p1",
                "payload": {},
                "confirm_token": "any",
            },
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_ACTION"


class TestExecuteSupabaseFailure:
    @pytest.mark.asyncio
    async def test_supabase_failure_returns_502(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        mock_execute_handlers: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_execute_handlers.side_effect = __import__(
            "app.agent.loop", fromlist=["UpstreamError"]
        ).UpstreamError("fail")

        payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token("create_watering_schedule", "p1", payload, "test-user-id")

        response = await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "p1",
                "payload": payload,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


class TestExecuteNoServiceRole:
    @pytest.mark.asyncio
    async def test_handler_receives_user_scoped_client(
        self,
        client: AsyncClient,
        mock_auth_verify: AsyncMock,
        mock_supabase_client_actions: AsyncMock,
        mock_execute_handlers: AsyncMock,
        auth_headers: dict,
    ) -> None:
        mock_auth_verify.return_value = {"id": "test-user-id"}
        mock_supabase_client_actions.return_value = "mock-scoped-client"
        mock_execute_handlers.return_value = "schedule-1"

        payload = {"frequency_days": 7, "next_due_at": "2025-06-08T00:00:00Z"}
        token = _make_token("create_watering_schedule", "plant-123", payload, "test-user-id")

        await client.post(
            "/actions/execute",
            json={
                "action_type": "create_watering_schedule",
                "plant_id": "plant-123",
                "payload": payload,
                "confirm_token": token,
            },
            headers=auth_headers,
        )

        mock_supabase_client_actions.assert_called_once()
        args = mock_supabase_client_actions.call_args.args
        assert args[2] == "test-valid-token"
