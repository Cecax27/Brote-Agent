"""End-to-end tests confirming the JSON-parse retry works through /chat.

These tests patch the underlying `_generate_once` (the Gemini API call site)
rather than `call_gemini` itself, so the retry logic in `call_gemini` runs
end-to-end.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient  # noqa: TC002

from app.supabase.context import ContextBundle


@pytest.fixture
def mock_generate():
    """Patch the Gemini API call inside the real call_gemini."""
    patcher = patch("app.agent.loop._generate_once", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


# Local SSE fixtures (the conftest only provides /chat fixtures).
@pytest.fixture
def mock_auth_sse():
    patcher = patch("app.auth.dependency.verify_access_token", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_client_sse():
    patcher = patch("app.api.sse_routes.build_user_client", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_supabase_context_sse():
    patcher = patch("app.api.sse_routes.build_plant_context", new_callable=AsyncMock)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def mock_conv_store_sse() -> dict:
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    patchers: dict = {}
    mocks: dict = {}
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
        patcher = patch(f"app.api.sse_routes.{name}", new_callable=AsyncMock)
        mocks[name] = patcher.start()
        patchers[name] = patcher

    dt = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)
    conv = MagicMock()
    conv.conversation_id = "conv-test-123"
    conv.user_id = "test-user-id"
    conv.plant_id = None
    conv.title = "Conversación con Flora"
    conv.created_at = dt
    conv.updated_at = dt

    mocks["create_conversation"].return_value = conv
    mocks["get_conversation"].return_value = conv
    mocks["fetch_history"].return_value = []

    yield mocks

    for patcher in patchers.values():
        patcher.stop()


@pytest.mark.asyncio
async def test_chat_succeeds_when_first_gemini_returns_bad_json(
    client: AsyncClient,
    mock_generate: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    """A truncated JSON reply on the first call should retry and succeed."""
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    bad = '{"reply": "Manch'
    good = json.dumps({"reply": "Recovered reply"})
    mock_generate.side_effect = [bad, good]

    response = await client.post("/chat", json={"message": "x"}, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Recovered reply"
    assert mock_generate.call_count == 2


@pytest.mark.asyncio
async def test_chat_502s_when_all_calls_return_bad_json(
    client: AsyncClient,
    mock_generate: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    """All three attempts truncated → standard 502."""
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    mock_generate.side_effect = [
        '{"reply": "cut',
        '{"reply": "still cut',
        '{"reply": "still cut again',
    ]

    response = await client.post("/chat", json={"message": "x"}, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"
    assert mock_generate.call_count == 3


@pytest.mark.asyncio
async def test_chat_succeeds_on_second_retry_when_first_retry_also_truncated(
    client: AsyncClient,
    mock_generate: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    """Both first and second attempts truncated → second retry succeeds."""
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])

    mock_generate.side_effect = [
        '{"reply": "cut',
        '{"reply": "still cut',
        json.dumps({"reply": "Recovered after escalation"}),
    ]

    response = await client.post("/chat", json={"message": "x"}, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Recovered after escalation"
    assert mock_generate.call_count == 3


@pytest.mark.asyncio
async def test_chat_user_message_persisted_when_all_retries_fail(
    client: AsyncClient,
    mock_generate: AsyncMock,
    mock_auth_verify: AsyncMock,
    mock_supabase_client: AsyncMock,
    mock_supabase_context: AsyncMock,
    mock_conversation_store: dict,
    auth_headers: dict,
) -> None:
    """Even after all retries fail, the user message survives (005 rule)."""
    mock_auth_verify.return_value = {"id": "test-user-id"}
    mock_supabase_context.return_value = ContextBundle(light=[])
    mock_generate.side_effect = [
        '{"reply": "cut',
        '{"reply": "still cut',
        '{"reply": "still cut again',
    ]

    response = await client.post("/chat", json={"message": "x"}, headers=auth_headers)

    assert response.status_code == 502
    append_calls = mock_conversation_store["append_message"].call_args_list
    assert len(append_calls) == 1
    assert append_calls[0][0][2] == "user"
    assert append_calls[0][0][3] == "x"


@pytest.mark.asyncio
async def test_chat_sse_succeeds_when_first_gemini_returns_bad_json(
    client: AsyncClient,
    mock_auth_sse: AsyncMock,
    mock_supabase_client_sse: AsyncMock,
    mock_supabase_context_sse: AsyncMock,
    mock_conv_store_sse: dict,
    mock_generate: AsyncMock,
    auth_headers: dict,
) -> None:
    """SSE path: retry on truncated JSON, second call succeeds.

    We patch `_generate_once` (the Gemini API call inside `call_gemini`)
    so the real `call_gemini` runs and the retry logic kicks in.
    """
    mock_auth_sse.return_value = {"id": "test-user-id"}
    mock_supabase_context_sse.return_value = ContextBundle(light=[])

    mock_generate.side_effect = [
        '{"reply": "truncated',
        json.dumps({"reply": "Recovered via SSE"}),
    ]

    response = await client.post(
        "/chat/stream",
        json={"message": "x"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    text = response.text
    blocks = [b for b in text.split("\n\n") if b.strip()]
    result_blocks = [b for b in blocks if b.startswith("event: result")]
    assert result_blocks, f"Expected result event in {text!r}"
    result_block = result_blocks[0]
    data_line = next(line for line in result_block.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    assert payload["reply"] == "Recovered via SSE"
    assert mock_generate.call_count == 2
