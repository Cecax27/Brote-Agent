from fastapi import Request
from fastapi.responses import JSONResponse

from app.actions.routes import InvalidActionError
from app.agent.loop import UpstreamError
from app.auth.tokens import AuthError
from app.logging import get_logger
from app.vision.images import InvalidImageError
from app.vision.retrieval import ImageNotFoundError

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


async def invalid_action_exception_handler(
    request: Request, exc: InvalidActionError
) -> JSONResponse:
    logger.warning("invalid_action", path=request.url.path)
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_ACTION",
                "message": "La acción solicitada no está permitida.",
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


async def invalid_image_exception_handler(
    request: Request, exc: InvalidImageError
) -> JSONResponse:
    logger.warning("invalid_image", path=request.url.path)
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_IMAGE",
                "message": str(exc),
            },
        },
    )


async def image_not_found_exception_handler(
    request: Request, exc: ImageNotFoundError
) -> JSONResponse:
    logger.warning("image_not_found", path=request.url.path)
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "IMAGE_NOT_FOUND",
                "message": "La foto solicitada no se encontró.",
            },
        },
    )
