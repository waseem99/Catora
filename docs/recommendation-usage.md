# Recommendation usage reporting

`GET /api/v1/workspaces/{workspace_id}/recommendation-usage` returns a tenant-scoped,
read-only reconciliation of persisted recommendation activity.

The report includes actual recommendation cost, provider/model and task breakdowns, job
status counts, retry volume, and the total budget ceiling currently exposed by queued or
running jobs. Optional `created_from` and exclusive `created_to` filters apply identically
to recommendation and job records.

Costs come only from persisted recommendations. Failed and cancelled jobs do not invent
provider cost. Active job budget is exposure, not spend, and is reported separately.
The endpoint requires workspace membership and does not expose request snapshots, provider
prompts, source content, or cross-workspace identifiers.
