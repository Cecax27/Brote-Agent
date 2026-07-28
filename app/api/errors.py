from fastapi import Request
from fastapi.responses import JSONResponse

from app.agent.loop import UpstreamError
from app.auth.tokens import AuthError
from app.logging import get_logger

logger = get_logger(__name__)


async def auth_exception_handler(request: Request, exc: AuthError) -> JSONResponse:
    logger.warning(
        "auth_error",
        path=request.url.path,
    )
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "UNAUTHORIZED",
                "message": str(exc),
            },
        },
    )


async def upstream_exception_handler(request: Request, exc: UpstreamError) -> JSONResponse:
    logger.warning(
        "upstream_error",
        path=request.url.path,
        error=str(exc),
    )
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "code": "UPSTREAM_ERROR",
                "message": str(exc),
            },
        },
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = getattr(exc, "errors", lambda: None)()
    logger.warning("validation_error", path=request.url.path, detail=str(detail))
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": str(detail) if detail else "Invalid request body",
            },
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_error",
        path=request.url.path,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        },
    )
