import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import boto3
import redis.asyncio as redis
import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from catora_api import __version__
from catora_api.api import (
    auth_router,
    catalog_router,
    ingestion_router,
    public_catalog_router,
    shopify_router,
)
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
app.include_router(shopify_router)
app.include_router(public_catalog_router)
app.include_router(catalog_router)
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
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    checks = await asyncio.gather(
        _timed_check("database", check_database),
        _timed_check("redis", _check_redis),
        _timed_check("object_storage", _check_object_storage),
    )
    healthy = all(result["ok"] for result in checks)
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if healthy else "not_ready", "checks": checks},
    )


async def _timed_check(
    name: str,
    check: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    try:
        await asyncio.wait_for(check(), timeout=settings.health_check_timeout_seconds)
        return {"name": name, "ok": True}
    except Exception as exc:
        return {"name": name, "ok": False, "error": type(exc).__name__}


async def _check_redis() -> None:
    client = redis.from_url(settings.redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_object_storage() -> None:
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)
