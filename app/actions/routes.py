from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

import app.actions.handlers as handlers_mod
from app.actions.audit import log_action_executed
from app.actions.models import payload_digest
from app.actions.registry import resolve_action
from app.actions.tokens import TokenAuthError, verify_confirm_token
from app.auth.dependency import UserIdentity, get_authenticated_user
from app.auth.tokens import AuthError
from app.logging import get_logger
from app.supabase.client import build_user_client

if TYPE_CHECKING:
    from app.config.settings import Settings

logger = get_logger(__name__)
actions_router = APIRouter()

AUTH_ERROR_MESSAGE = "Debes iniciar sesión para continuar."


class ExecuteRequest(BaseModel):
    action_type: str
    plant_id: str
    payload: dict
    confirm_token: str


class ExecuteResponse(BaseModel):
    action_id: str
    action_type: str
    status: str


class InvalidActionError(Exception):
    pass


@actions_router.post("/actions/execute", status_code=201)
async def execute_action(
    body: ExecuteRequest,
    request: Request,
    user: UserIdentity = Depends(get_authenticated_user),  # noqa: B008, FAST002
) -> ExecuteResponse:
    settings: "Settings" = request.app.state.settings
    start = time.monotonic()

    spec = resolve_action(body.action_type)
    if spec is None:
        raise InvalidActionError

    try:
        verify_confirm_token(
            body.confirm_token,
            body.action_type,
            body.plant_id,
            body.payload,
            user.sub,
            settings.action_signing_secret,
        )
    except TokenAuthError:
        raise AuthError(AUTH_ERROR_MESSAGE) from None

    handler = getattr(handlers_mod, body.action_type, None)
    if handler is None:
        raise InvalidActionError

    client = await build_user_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        user.access_token,
    )

    try:
        action_id = await handler(client, body.plant_id, user.sub, body.payload)
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log_action_executed(
            action_type=body.action_type,
            table=spec.table,
            plant_id=body.plant_id,
            action_id=None,
            user_sub=user.sub,
            status="upstream_error",
            duration_ms=elapsed_ms,
            payload_digest=payload_digest(body.payload, body.plant_id),
        )
        raise

    elapsed_ms = int((time.monotonic() - start) * 1000)
    log_action_executed(
        action_type=body.action_type,
        table=spec.table,
        plant_id=body.plant_id,
        action_id=action_id,
        user_sub=user.sub,
        status="executed",
        duration_ms=elapsed_ms,
        payload_digest=payload_digest(body.payload, body.plant_id),
    )

    return ExecuteResponse(
        action_id=action_id,
        action_type=body.action_type,
        status="executed",
    )
