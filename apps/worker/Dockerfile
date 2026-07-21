FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api /app
RUN pip install --no-cache-dir .
CMD ["celery", "-A", "catora_api.worker:celery_app", "worker", "--loglevel=INFO"]
