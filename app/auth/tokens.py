import jwt

from app.logging import get_logger

logger = get_logger(__name__)

AUTH_ERROR_MESSAGE = "Debes iniciar sesión para continuar."


class AuthError(Exception):
    """The access token is missing, malformed, expired, or has a bad signature."""


def verify_access_token(token: str, *, secret: str, audience: str, issuer: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("auth_token_expired")
        raise AuthError(AUTH_ERROR_MESSAGE) from None
    except jwt.InvalidTokenError:
        logger.warning("auth_token_invalid")
        raise AuthError(AUTH_ERROR_MESSAGE) from None

    sub = claims.get("sub")
    if not isinstance(sub, str):
        logger.warning("auth_token_missing_sub")
        raise AuthError(AUTH_ERROR_MESSAGE)

    logger.info("auth_token_verified", sub=sub)
    return claims
