import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import boto3
import redis.asyncio as redis
import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from catora_api import __version__
from catora_api.api import auth_router, ingestion_router
from catora_api.auth.service import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidTokenError,
)
from catora_api.config import Settings, get_settings
from catora_api.database import check_database, engine


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(
    title="Catora API",
    version=__version__,
    description="Enterprise ecommerce catalog intelligence API",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(ingestion_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(AuthenticationError)
async def authentication_error(_: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(AuthorizationError)
async def authorization_error(_: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_error(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidTokenError)
async def invalid_token_error(_: Request, exc: InvalidTokenError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    response: Response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "catora-api", "version": __version__}


async def _check_redis(settings: Settings) -> None:
    client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, socket_connect_timeout=2
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_storage(settings: Settings) -> None:
    def check() -> None:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        client.list_buckets()

    await asyncio.to_thread(check)


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    checks: dict[str, Callable[[], Awaitable[None]]] = {
        "postgres": check_database,
        "redis": lambda: _check_redis(settings),
        "object_storage": lambda: _check_storage(settings),
    }
    dependencies: list[dict[str, str]] = []
    for name, check in checks.items():
        try:
            await check()
            dependencies.append({"name": name, "status": "ok"})
        except Exception as exc:  # readiness must report dependency failure, not leak internals
            dependencies.append({"name": name, "status": "error", "detail": type(exc).__name__})

    ready = all(item["status"] == "ok" for item in dependencies)
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready else "not_ready", "dependencies": dependencies},
    )


@app.get("/api/v1/system/info", tags=["system"])
async def system_info() -> dict[str, str]:
    return {"name": "Catora", "version": __version__, "environment": settings.environment}
