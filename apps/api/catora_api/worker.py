from celery import Celery

from catora_api.config import get_settings

settings = get_settings()
celery_app = Celery("catora", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=900,
    task_soft_time_limit=840,
    worker_prefetch_multiplier=1,
    imports=(
        "catora_api.ingestion.tasks",
        "catora_api.auditing.tasks",
        "catora_api.enrichment.tasks",
        "catora_api.demo.tasks",
        "catora_api.diagnostics.tasks",
        "catora_api.shopify.tasks",
    ),
)


@celery_app.task(name="catora.system.ping")  # type: ignore[misc]
def ping() -> dict[str, str]:
    return {"status": "ok", "worker": "catora"}
