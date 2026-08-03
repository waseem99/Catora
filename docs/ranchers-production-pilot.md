# Ranchers production pilot status

Ranchers is the first intended consumer of the generic restaurant pilot acceptance gate. The repository implementation does not establish authority over Ranchers systems and does not claim that Ranchers is connected or activated.

## Repository-ready capabilities

The repository contains feature-gated, evidence-first foundations for:

- restaurant brand, branch, menu, item, modifier, offer and freshness contracts;
- a push-only Restaurant Catalog Bridge with restricted-field rejection;
- technical and on-page restaurant audit rules;
- answer-readiness evaluation from persisted facts;
- governed Git proposal branches and draft pull requests;
- synthetic/read-only local-profile and reputation intelligence;
- aggregate measurement observations and correlation-only comparisons;
- evidence-backed authority observations with non-sendable outreach drafts;
- reconciled operations snapshots, bounded exports, alerts, actions and monitor runs;
- generic production pilot plans, checks, decisions and disconnect evidence.

These capabilities remain default-off. Provider modules that have not completed account-level acceptance remain unavailable.

## External evidence still required

A Ranchers plan cannot reach `ready_for_external_acceptance` without dated evidence for:

- the Ranchers business owner;
- the Ranchers backend/data owner;
- the website repository owner;
- security and privacy approval;
- SEO/visibility approval;
- deployment and rollback ownership;
- operator acceptance;
- safe non-production backend access;
- an approved catalog/menu/branch allowlist;
- website repository and production website access;
- deployment-platform access;
- production build and smoke evidence;
- conformance, replay, tenant isolation and restricted-field tests;
- backup/restore, rollback and disconnect rehearsals;
- ordering and deployment isolation;
- a sanitized manager report bundle.

Search Console, analytics, Google Business Profile, review and authority-provider access are optional for the minimum platform gate but must remain visibly unavailable until accepted.

## Prohibited representations

Until the external evidence exists, Catora must not claim that it:

- is connected to the Ranchers backend or database;
- reads live Ranchers menu or branch data;
- can modify orders, prices or availability;
- controls the Ranchers website repository or deployment platform;
- has Search Console, analytics, business-profile, review or backlink-provider access;
- has completed Ranchers manager acceptance;
- has activated a production Ranchers pilot.

## Activation boundary

The generic gate can record a hashed external authorization reference after all repository checks pass. Even then, its contract returns:

```text
live_activation_allowed = false
live_activation_performed = false
```

Actual source/provider enablement must occur through separately reviewed connector and platform procedures owned by the external system owners. There is no activation endpoint in the pilot gate.

## Issue closure

Issue #222 should remain open after the generic gate merges. It may close only when the actual Ranchers owners, access grants and acceptance evidence are recorded and independently verified. Repository green status is necessary but not sufficient.
