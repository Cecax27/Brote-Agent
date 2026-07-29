from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.actions.routes import InvalidActionError, actions_router
from app.agent.loop import UpstreamError
from app.api.errors import (
    auth_exception_handler,
    generic_exception_handler,
    image_not_found_exception_handler,
    invalid_action_exception_handler,
    invalid_image_exception_handler,
    upstream_exception_handler,
    validation_exception_handler,
)
from app.api.routes import router
from app.auth.tokens import AuthError
from app.config.settings import Settings
from app.logging import configure_logging, get_logger
from app.vision.images import InvalidImageError
from app.vision.retrieval import ImageNotFoundError
from app.vision.routes import router as vision_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(app.state.settings)
    logger.info("startup", port=app.state.settings.port)
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]

    app = FastAPI(
        title="Brote Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(InvalidActionError, invalid_action_exception_handler)
    app.add_exception_handler(InvalidImageError, invalid_image_exception_handler)
    app.add_exception_handler(ImageNotFoundError, image_not_found_exception_handler)
    app.add_exception_handler(UpstreamError, upstream_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    app.include_router(router)
    app.include_router(actions_router)
    app.include_router(vision_router)

    return app


app = create_app()
