# Asynchronous recommendation jobs

Catora persists recommendation execution requests as tenant-scoped jobs and executes them through
Celery. This keeps provider latency outside HTTP request lifetimes and makes queue, running,
completed and failed states queryable.

- `POST /api/v1/workspaces/{workspace_id}/recommendation-jobs` queues a job.
- `GET /api/v1/workspaces/{workspace_id}/recommendation-jobs` lists jobs with exact pagination
  totals and optional product/status filters.
- `GET /api/v1/workspaces/{workspace_id}/recommendation-jobs/{job_id}` returns one job.

Source content is redacted before the request snapshot is stored. Job responses never expose that
snapshot. The worker commits `running` before provider execution, then commits the append-only
recommendation and `completed` state together. Failures roll back partial recommendation objects,
store a bounded non-sensitive failure summary and emit an audit event.

The deterministic mock adapter remains development/test-only. A production provider adapter is a
separate implementation.
