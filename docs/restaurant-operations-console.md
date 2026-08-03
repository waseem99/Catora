# Restaurant operations console

The restaurant operations console reconciles persisted Catora evidence into immutable, workspace-scoped snapshots. It does not accept caller-supplied KPI values and it does not execute fixes, publish content, send outreach, connect providers, change ordering systems, or mutate restaurant availability.

## Feature gates

Both gates default to `false`:

- `CATORA_RESTAURANT_OPERATIONS_CONSOLE_ENABLED` exposes snapshot, export, alert and action-review APIs.
- `CATORA_RESTAURANT_MONITORING_ENABLED` exposes schedules and monitor runs and requires the console gate.

A monitor may record an intended notification channel. Catora does not send that notification in this implementation; every run records `notification_sent=false`.

## Persisted sources

Snapshots derive from workspace-scoped records only:

- restaurant fact observations for catalog freshness;
- completed audit runs and findings for technical/on-page visibility;
- restaurant answer runs and results for answer readiness;
- local-profile accounts, observations, links and conflicts;
- review accounts, observations, analyses and response drafts;
- aggregate measurement accounts and observations;
- authority accounts, observations and opportunities;
- governed Git repository connections and proposals.

A missing source is `unavailable`, not zero. A disconnected account is `disconnected`. Evidence older than the section policy becomes `stale`. Incomplete or sampled evidence becomes `partial`. Critical evidence that requires a human decision becomes `blocked`.

## Metric contract

Every metric includes:

- a stable metric key and definition version;
- a value and unit;
- source coverage;
- source references;
- observation and optional window timestamps.

Snapshots and exports set both `causal_claim_allowed=false` and `direct_mutation_allowed=false`. Measurement remains correlation-only and reports make no ranking, citation, traffic, conversion, revenue or ROI promise.

## API surface

The tenant-scoped API supports:

- generating and reading snapshots;
- generating bounded JSON or CSV exports;
- listing, acknowledging and resolving alerts;
- listing and deciding evidence-linked action proposals;
- listing and updating monitor schedules;
- running a schedule explicitly and reading its run history.

There are no console routes for `fix`, `publish`, `deploy`, `merge`, `send`, provider connection, ordering, or availability mutation.

## Exports

Exports are deterministic, versioned and limited to 5 MiB. They contain only the reconciled snapshot contract, not raw review text, reviewer identities, provider credentials, cookies, sessions, customer/order records or secrets. Restricted field names fail closed before an export record is persisted.

## Monitoring

Supported cadences are hourly, daily, weekly and monthly. Hourly is the minimum interval. Schedules use an IANA timezone and store the next due instant in UTC. Runs have workspace-level idempotency keys derived from the schedule and due instant.

Monitor runs:

1. lock the schedule;
2. refuse disabled schedules;
3. reconcile selected persisted sections;
4. create or reuse an immutable snapshot;
5. deduplicate alerts and action proposals;
6. record a completed run and advance the next due instant.

No scheduler daemon or external notification provider is activated by the feature gate alone.

## Alert and action lifecycle

Alerts are fingerprinted from section, state, detail and evidence. Repeated snapshots reuse the alert. When a later snapshot no longer contains the evidence state, the open alert is resolved with an audit note.

Actions identify the owner role, target workflow, evidence and independent verification method. Human decisions may mark them approved, rejected, completed or blocked. Approval never executes the target workflow.

## Migration and rollback

Alembic revision `0027` adds snapshots, alerts, actions, schedules, monitor runs and exports after `0026`. The required acceptance sequence is:

```bash
alembic upgrade 0027
alembic downgrade 0026
alembic upgrade 0027
```

Rollback disables both feature gates and downgrades only after retaining required report and audit history. Disabling monitoring stops new runs without deleting prior snapshots, exports, alerts, decisions or run records.
