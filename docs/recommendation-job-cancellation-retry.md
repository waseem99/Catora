# Recommendation job cancellation and retry

Queued recommendation jobs may be cancelled before worker execution. Running, completed and failed
jobs are not presented as interruptible, because the configured provider call may already be in
progress. A delivered Celery task exits without provider execution when it sees a cancelled job.

Retries are append-only. A retry creates a new queued job linked through `retry_of_job_id`; the
original failed job and its bounded failure summary remain unchanged. Each failed job can have at
most one direct child retry, producing a linear retry chain, and the chain depth is capped by the
configured workspace service limit.

Retry creation revalidates the stored request, applies the current workspace enrichment policy,
uses the current configured provider, and cannot increase the previous job budget. Cancellation and
retry actions are tenant-scoped, require recommendation-write permission and emit immutable audit
events.
