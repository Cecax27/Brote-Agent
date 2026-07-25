from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.agent.loop import UpstreamError
from app.api.errors import (
    generic_exception_handler,
    upstream_exception_handler,
    validation_exception_handler,
)
from app.api.routes import router
from app.config.settings import Settings
from app.logging import configure_logging, get_logger

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

    app.add_exception_handler(UpstreamError, upstream_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    app.include_router(router)

    return app


app = create_app()
