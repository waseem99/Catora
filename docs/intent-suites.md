# Saved buyer-intent suites and coverage reruns

A saved intent suite is an immutable ordered set of exact approved buyer-intent versions. Creating a
suite never follows a lineage to a newer version later: every member stores the exact
`buyer_intent_id`, lineage, version, and position selected by the user.

Suite creation and execution require the existing `analysis.run` capability and CSRF protection.
Workspace members may read suite definitions and completed suite-run results. The backend endpoints
are:

- `GET|POST /api/v1/workspaces/{workspace_id}/intent-suites`
- `GET /api/v1/workspaces/{workspace_id}/intent-suites/{suite_id}`
- `POST /api/v1/workspaces/{workspace_id}/intent-suites/{suite_id}/runs`
- `GET /api/v1/workspaces/{workspace_id}/intent-suite-runs/{run_id}`

Executing a suite calls the existing deterministic `IntentRunService` once per pinned member. Each
child intent run remains an append-only first-class run and is associated with the suite run through
`intent_suite_run_id`. Requested product IDs use the same active, non-deleted, tenant-scoped
validation as standalone runs.

Coverage uses all persisted child `IntentProductMatch` rows. The denominator is the total number of
product or variant targets evaluated across every suite member. Confident coverage is stored and
returned in basis points using integer floor division; an empty target set returns zero. Counts for
all four deterministic states reconcile to the target count.

A completed suite run records a SHA-256 snapshot over the stable suite ID, ordered pinned members,
sorted requested product selection, and each child run snapshot hash. The immediately previous
completed run for the same suite is linked through `previous_run_id`, and the API returns signed
count and confident-coverage deltas using identical denominator semantics.

Revision `0015` adds suite, member, and suite-run tables plus the nullable child-run association. No
provider call, automatic approval, frontend behavior, or catalog write is introduced by this slice.
