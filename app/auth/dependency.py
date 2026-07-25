from fastapi import Request

from app.auth.tokens import verify_access_token, AuthError, AUTH_ERROR_MESSAGE
from app.logging import get_logger

logger = get_logger(__name__)


class UserIdentity:
    def __init__(self, sub: str) -> None:
        self.sub = sub

    def __repr__(self) -> str:
        return f"UserIdentity(sub={self.sub})"


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

    issuer = f"{settings.supabase_url}/auth/v1"
    claims = verify_access_token(
        token,
        secret=settings.supabase_jwt_secret,
        audience=settings.auth_jwt_audience,
        issuer=issuer,
    )

    return UserIdentity(sub=claims["sub"])
