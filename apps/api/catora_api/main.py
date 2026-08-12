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
from catora_api.api import (
    audit_rules_router,
    audits_router,
    auth_router,
    authority_router,
    catalog_bridge_router,
    catalog_identity_router,
    catalog_router,
    demo_router,
    diagnostics_router,
    enrichment_policy_router,
    git_publishing_router,
    ingestion_router,
    intent_parsing_router,
    intent_runs_router,
    intent_templates_router,
    intents_router,
    local_profiles_router,
    measurement_router,
    operations_console_router,
    public_catalog_router,
    recommendations_router,
    reputation_router,
    restaurant_answers_router,
    restaurant_bridge_router,
    restaurant_pilot_router,
    service_visibility_router,
    shopify_router,
    taxonomy_router,
)
from catora_api.auth.service import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidTokenError,
)
from catora_api.config import Settings, get_settings
from catora_api.database import check_database, engine
from catora_api.release_identity import runtime_release_identity


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
    description="Enterprise catalog, restaurant and service visibility intelligence API",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(catalog_bridge_router)
app.include_router(restaurant_bridge_router)
app.include_router(shopify_router)
app.include_router(public_catalog_router)
app.include_router(catalog_router)
app.include_router(catalog_identity_router)
app.include_router(taxonomy_router)
app.include_router(audits_router)
app.include_router(audit_rules_router)
app.include_router(recommendations_router)
app.include_router(service_visibility_router)
app.include_router(restaurant_answers_router)
app.include_router(git_publishing_router)
app.include_router(local_profiles_router)
app.include_router(reputation_router)
app.include_router(measurement_router)
app.include_router(authority_router)
app.include_router(operations_console_router)
app.include_router(restaurant_pilot_router)
app.include_router(enrichment_policy_router)
app.include_router(intent_parsing_router)
app.include_router(intent_runs_router)
app.include_router(intent_templates_router)
app.include_router(intents_router)
app.include_router(demo_router)
app.include_router(diagnostics_router)
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
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
    )
    response: Response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "catora-api",
        "version": __version__,
    }


@app.get("/health/release", tags=["health"])
async def release_identity() -> dict[str, object]:
    return runtime_release_identity("api")


def _worker_ping() -> dict[str, object]:
    from catora_api.worker import celery_app

    result = celery_app.send_task("catora.system.ping")
    try:
        payload = result.get(timeout=8)
    finally:
        result.forget()
    if not isinstance(payload, dict):
        raise RuntimeError("Worker ping returned an invalid payload")
    return payload


@app.get("/health/worker", tags=["health"])
async def worker_health() -> JSONResponse:
    try:
        payload = await asyncio.to_thread(_worker_ping)
        release = payload.get("release")
        if payload.get("status") != "ok" or not isinstance(release, dict):
            raise RuntimeError("Worker ping did not prove a running worker release")
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "detail": type(exc).__name__},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)


async def _check_redis(settings: Settings) -> None:
    client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        socket_connect_timeout=2,
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
        client.list_objects_v2(Bucket=settings.s3_bucket, MaxKeys=1)

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
        except Exception as exc:
            dependencies.append(
                {
                    "name": name,
                    "status": "error",
                    "detail": type(exc).__name__,
                }
            )

    ready = all(item["status"] == "ok" for item in dependencies)
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if ready
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content={
            "status": "ready" if ready else "not_ready",
            "dependencies": dependencies,
        },
    )


@app.get("/api/v1/system/info", tags=["system"])
async def system_info() -> dict[str, str]:
    return {
        "name": "Catora",
        "version": __version__,
        "environment": settings.environment,
    }
