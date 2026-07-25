import httpx

from app.logging import get_logger

logger = get_logger(__name__)

AUTH_ERROR_MESSAGE = "Debes iniciar sesión para continuar."


class AuthError(Exception):
    """The access token is missing, malformed, expired, or invalid."""


async def verify_access_token(url: str, token: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": token,
                },
            )
    except httpx.HTTPError as exc:
        logger.exception("auth_verify_network_error")
        raise AuthError(AUTH_ERROR_MESSAGE) from exc

    if response.status_code == 200:
        data = response.json()
        sub = data.get("id")
        if not isinstance(sub, str):
            logger.warning("auth_token_missing_sub")
            raise AuthError(AUTH_ERROR_MESSAGE)
        logger.info("auth_token_verified", sub=sub)
        return data

    logger.warning("auth_token_invalid", status=response.status_code)
    raise AuthError(AUTH_ERROR_MESSAGE)
