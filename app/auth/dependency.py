from fastapi import Request

from app.auth.tokens import AUTH_ERROR_MESSAGE, AuthError, verify_access_token
from app.logging import get_logger

logger = get_logger(__name__)


class UserIdentity:
    def __init__(self, sub: str, access_token: str, display_name: str | None = None) -> None:
        self.sub = sub
        self.access_token = access_token
        self.display_name = display_name

    def __repr__(self) -> str:
        return f"UserIdentity(sub={self.sub})"


def _extract_display_name(data: dict) -> str | None:
    user_meta = data.get("user_metadata")
    if isinstance(user_meta, dict):
        name = user_meta.get("display_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


async def get_authenticated_user(request: Request) -> UserIdentity:
    settings = request.app.state.settings

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        logger.warning("auth_header_missing")
        raise AuthError(AUTH_ERROR_MESSAGE)

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        logger.warning("auth_header_malformed")
        raise AuthError(AUTH_ERROR_MESSAGE)

    data = await verify_access_token(settings.supabase_url, token)
    return UserIdentity(
        sub=data["id"],
        access_token=token,
        display_name=_extract_display_name(data),
    )
