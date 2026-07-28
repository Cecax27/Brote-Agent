from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time

from app.actions.models import payload_digest
from app.logging import get_logger

logger = get_logger(__name__)

# In-process nonce store. Cloud Run instances are short-lived and each
# serves many requests; a nonce observed here is checkable here. Replay
# from a different instance is bounded by the 5-min TTL. This is accepted
# for V1.0 — the impact is at most one extra row.
_nonce_store: dict[str, float] = {}


def _prune_expired() -> None:
    now = time.time()
    expired = [n for n, exp in _nonce_store.items() if exp < now]
    for n in expired:
        del _nonce_store[n]


class TokenAuthError(Exception):
    pass


class InvalidActionError(Exception):
    pass


def issue_confirm_token(  # noqa: PLR0913, PLR0917
    action_type: str,  # noqa: ARG001
    plant_id: str,
    payload: dict,
    user_sub: str,
    signing_secret: str,
    ttl_seconds: int = 300,
) -> str:
    _prune_expired()
    nonce = secrets.token_hex(16)
    exp = int(time.time()) + ttl_seconds
    digest = payload_digest(payload, plant_id)
    data = f"{digest}:{user_sub}:{exp}:{nonce}"
    mac = hmac.new(
        signing_secret.encode(),
        data.encode(),
        hashlib.sha256,
    ).digest()

    token_body = base64.urlsafe_b64encode(nonce.encode() + mac).rstrip(b"=").decode()
    token = f"{token_body}:{exp}"
    _nonce_store[nonce] = exp
    logger.debug("confirm_token_issued")
    return token


def verify_confirm_token(  # noqa: PLR0913, PLR0917
    token: str,
    action_type: str,  # noqa: ARG001
    plant_id: str,
    payload: dict,
    user_sub: str,
    signing_secret: str,
) -> None:
    _prune_expired()

    try:
        token_body, exp_str = token.rsplit(":", 1)
        exp = int(exp_str)
    except (ValueError, OverflowError):
        raise TokenAuthError from None

    if exp < time.time():
        raise TokenAuthError

    try:
        decoded = base64.urlsafe_b64decode(token_body + "==")
    except (ValueError, binascii.Error):
        raise TokenAuthError from None

    nonce_bytes = decoded[:32]
    mac = decoded[32:]

    try:
        nonce = nonce_bytes.decode()
    except UnicodeDecodeError:
        raise TokenAuthError from None

    if nonce not in _nonce_store:
        raise TokenAuthError

    digest = payload_digest(payload, plant_id)
    data = f"{digest}:{user_sub}:{exp}:{nonce}"
    expected_mac = hmac.new(
        signing_secret.encode(),
        data.encode(),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(mac, expected_mac):
        raise TokenAuthError

    del _nonce_store[nonce]
    logger.debug("confirm_token_verified")
