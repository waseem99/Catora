# Restaurant pilot production acceptance

Catora's restaurant pilot acceptance gate records evidence and human decisions. It does not connect a client, access a production system, execute a sync, publish a change, deploy code, mutate a provider, or activate a pilot.

## Feature gate

`CATORA_RESTAURANT_PILOT_ACCEPTANCE_ENABLED` defaults to `false`. The flag exposes only generic plan, check, readiness, decision and disconnect-evidence APIs. It is not a client-specific activation flag.

There is no Ranchers-only core table, contract or runtime switch.

## Required owners

Every production plan requires one independently identified owner for:

- business authorization;
- backend data access and field policy;
- website repository access;
- security and privacy;
- SEO and visibility acceptance;
- deployment and rollback;
- operator acceptance.

An approved owner record requires a date and evidence reference. A name in an issue or repository is not sufficient evidence of external-system authority.

## Access evidence

The required systems are:

- restaurant backend;
- website repository;
- production website;
- deployment platform.

Accepted access requires a dated evidence reference and a managed credential reference using `env:`, `vault:` or `secret:`. Raw credentials and references containing secret values fail validation.

Optional provider access remains visible as unavailable or revoked. Missing Search Console, analytics, business-profile, review or authority-provider access must not be represented as active.

## Field policy

The plan must include an approved field allowlist. The following domains are always prohibited:

- customers;
- orders;
- payments and payment methods;
- refunds;
- loyalty;
- passwords;
- sessions;
- tokens and API keys.

Approved fields cannot contain customer, order, payment, session, token or password domains. The Catalog Bridge remains push-only and Catora has no order or write-back path.

## Required checks

A plan cannot become ready for external acceptance until all checks have passed with evidence hash, timestamp and reviewer:

1. production build live;
2. production smoke test;
3. safe non-production access;
4. Catalog Bridge conformance;
5. snapshot reconciliation;
6. replay idempotency;
7. tenant isolation;
8. restricted-field rejection;
9. backup and restore;
10. rollback rehearsal;
11. disconnect and restore;
12. ordering-path isolation;
13. deployment isolation;
14. sanitized report bundle;
15. operator acceptance.

Snapshot reconciliation requires:

```text
source = accepted + excluded + rejected
normalized = accepted
```

Ordering and deployment isolation checks fail if an impact was observed. Restricted-field rejection fails if any restricted field was accepted.

## Readiness states

- `blocked`: at least one owner, access grant, module or check is incomplete, failed, expired or inconsistent.
- `ready_for_external_acceptance`: repository and submitted evidence are complete; external authorization is still required.
- `external_acceptance_recorded`: a hashed external authorization reference was recorded.

All readiness responses preserve:

```text
external_authorization_required = true
live_activation_allowed = false
live_activation_performed = false
```

Recording external acceptance is an audit record. It does not invoke an activation or integration operation.

## Decisions

The API can record:

- a request for external acceptance;
- external acceptance evidence;
- rejection;
- rollback evidence.

Decisions bind to the exact readiness hash. A changed or stale readiness state cannot be approved. The API contains no `activate`, `connect`, `sync-production`, `publish`, `merge`, `deploy`, `orders`, `prices` or `availability` operation.

## Disconnect and rollback

Disconnect records are idempotent. A passed disconnect requires source access to be revoked and must report no ordering or deployment impact. Provider revocation remains explicit because optional providers may not have been connected.

Rollback contracts require:

- a named rollback owner;
- a runbook;
- a source-disable method;
- an independent provider-revoke method;
- no ordering dependency;
- no deployment dependency;
- no direct database dependency.

## Migration acceptance

Alembic revision `0028` follows `0027` and adds generic plans, checks, decisions and disconnect runs. The release sequence is:

```bash
alembic upgrade 0028
alembic downgrade 0027
alembic upgrade 0028
```

A code merge is not external client acceptance. A client-specific pilot issue remains open until the actual owners, accounts and dated acceptance evidence exist.
