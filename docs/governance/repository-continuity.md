# Repository continuity, recovery and emergency release policy

## Status snapshot — August 3, 2026

| Control | Current verified state | Acceptance state |
| --- | --- | --- |
| Canonical repository | `waseem99/Catora` | Verified |
| Canonical branch | `main` | Verified |
| Repository owner type | Personal GitHub account | Temporary / not a shared-continuity model |
| Authorized repository administrators | One: `@waseem99` | Backup administrator required |
| Independent approving reviewers | None recorded | Required before protected-review acceptance |
| Branch inventory | `main` only | Verified after branch-hygiene cleanup |
| Organization ownership | Not established | Required |
| Enforced `main` ruleset | Not independently evidenced | Required |
| Administrator-bypass test | Not independently evidenced | Required |

This record deliberately does not claim shared continuity, independent review, or protected-branch acceptance. Repository control is currently concentrated in one personal account. The source-controlled governance contract verifies provenance and current authority; it cannot replace GitHub organization ownership, repository-administration settings, or a second human's accepted responsibility.

## Target continuity model

Catora should be owned by a dedicated GitHub organization or an equivalent shared administrative structure with:

1. at least two trusted repository administrators using separate named accounts;
2. a repository/release owner responsible for branch protection, releases and emergency rollback;
3. a backend/data reviewer responsible for migrations, data contracts and production-job safety;
4. a security/privacy reviewer responsible for secrets, tenant isolation, provider access and retention;
5. independent approval for migration, deployment, security and external-integration changes;
6. least-privilege access, protected `main`, audit-logged emergency bypass and periodic access review.

One person may temporarily hold more than one operational role, but protected changes still require an independent approving account. A bot, GitHub App, shared credential or alternate account controlled by the same person is not an independent reviewer.

## Organization-transfer acceptance

The repository may be marked organization-owned only after all of the following are recorded in an approved private governance location:

- organization name and verified owners;
- repository transfer date and resulting canonical URL;
- primary and backup repository administrators;
- billing/recovery contacts where applicable;
- installed GitHub Apps and their approved permissions;
- updated deployment, package, Shopify and WordPress repository references;
- successful post-transfer workflow, deployment and rollback verification.

Do not update canonical repository metadata or `CODEOWNERS` merely in anticipation of a transfer. Update them in the same reviewed change that records the accepted owners and verifies the new repository.

## Protected `main` acceptance

The final ruleset or branch-protection configuration must:

- require pull requests for `main`;
- require the authoritative CI, security, governance, deployment, backup/restore, Catalog Bridge, Service Visibility, Shopify, hosted-availability, Northstar and prospect-diagnostic checks;
- block while checks are pending, skipped unexpectedly or failing;
- require the branch to be current before merge;
- dismiss stale approvals when the head changes;
- require at least one independent approving reviewer for migration, deployment, security and integration changes;
- apply to administrators;
- prohibit force pushes and deletion of `main`;
- restrict emergency bypass to named administrators, require a reason, and retain audit evidence.

Acceptance evidence must include a private screenshot or exported ruleset record and a test pull request proving that a failing required check cannot merge, including when attempted by an administrator.

## Account recovery

Private recovery material must never be committed to this repository.

The approved private governance location should record:

- organization-owner and repository-admin accounts;
- enforced two-factor authentication and approved passkey/security-key policy;
- recovery contacts and escalation order;
- location of recovery codes or emergency credentials in an approved secret manager;
- domain, billing and GitHub support recovery contacts where applicable;
- date of the most recent recovery drill.

A recovery drill should verify that the backup administrator can access repository settings, Actions, security alerts and deployment ownership without using another person's session or credentials.

## Emergency release procedure

1. Open a private incident record and identify severity, affected deployment and customer impact.
2. Prefer rollback to the last accepted Railway/Vercel release over an unreviewed forward fix.
3. If an emergency code change is required, create a focused branch and pull request, run every available required check and obtain independent approval whenever an independent reviewer is available.
4. If a documented administrator bypass is unavoidable, record the actor, reason, checks unavailable, exact commit, deployment, rollback plan and expiry of the exception.
5. Verify Railway API, Railway worker, Vercel, database migration state and hosted availability after the action.
6. Complete a post-incident review and revoke any temporary access or credentials.

An emergency bypass never authorizes disabling tenant isolation, secret protection, migration integrity, audit evidence, provider boundaries or the prohibition on autonomous customer-system writes.

## Access removal

When an administrator, reviewer, contractor or integration no longer requires access:

1. remove GitHub organization and repository roles;
2. revoke GitHub App, deploy key, personal-access-token and Actions-secret access that was specific to that person or integration;
3. remove or rotate Railway, Vercel, DNS, object-storage, database, Shopify, WordPress and provider credentials as applicable;
4. remove the account from private incident, recovery and secret-management systems;
5. review recent audit events, pull requests, workflow approvals and deployments;
6. update `CODEOWNERS`, support/security contacts and the private continuity record;
7. verify that production and rollback procedures still work with the remaining authorized team.

## CODEOWNERS rule

The current `CODEOWNERS` file correctly names the only verified administrator, `@waseem99`. Additional owners must not be added until each named person has accepted the specific role and has the corresponding repository permission. The accepted change should add role-appropriate path ownership rather than granting every reviewer ownership of every path.

## Acceptance record

Shared continuity is accepted only when a private record contains:

- acceptance date;
- organization and canonical repository;
- primary and backup administrator GitHub logins;
- repository/release, backend/data and security/privacy role assignments;
- accepted ruleset export or screenshots;
- protected failing-check test pull request;
- independent reviewer approval evidence;
- recovery drill result;
- branch inventory result;
- approving human names and roles.

Until that record exists, the machine-readable state remains `pending_external_admin_acceptance` and issue #235 must remain open.
