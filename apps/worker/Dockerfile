FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api /app
RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10001 catora \
    && useradd --system --uid 10001 --gid catora --create-home --home-dir /home/catora catora \
    && chown -R catora:catora /app
USER catora
CMD ["celery", "-A", "catora_api.worker:celery_app", "worker", "--beat", "--schedule=/tmp/catora-celerybeat", "--loglevel=INFO", "--concurrency=2", "--prefetch-multiplier=1", "--max-tasks-per-child=100", "--without-gossip", "--without-mingle"]
