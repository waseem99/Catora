# Repository ownership and release authority

## Verified repository-side authority

| Field | Verified value |
| --- | --- |
| Repository | `waseem99/Catora` |
| Repository owner | `@waseem99` |
| Authorized repository representative | `@waseem99` |
| Permission verified | GitHub administrator |
| Verification date | July 29, 2026 |
| Authority scope | Repository administration, code review, merges, workflows, release artifacts, and repository security/support triage |

The connected GitHub account is the repository owner and has administrator permission. `.github/CODEOWNERS` routes all repository paths, governance policies, and release-bearing integration surfaces to the same owner representative.

The machine-readable companion record is [`repository-authority.json`](repository-authority.json). CI validates that the repository slug, owner, CODEOWNERS routing, policy files, and public documentation remain consistent.

## Evidence chain

Repository-side authority is established through all of the following:

1. GitHub repository metadata names `waseem99` as the owner of `waseem99/Catora`.
2. The authenticated account `waseem99` has administrator permission on the repository.
3. The default branch is `main` and release work is integrated through reviewed pull requests and passing workflows.
4. `.github/CODEOWNERS` names `@waseem99` as the default owner for every path.
5. `SECURITY.md` and `SUPPORT.md` identify the same representative for repository-scoped triage and release decisions.
6. Package and integration metadata link back to the canonical repository rather than an unrelated publisher location.

## Continuity status

Repository authority and repository continuity are separate controls. The current verified owner can administer and release this repository, but the repository remains owned by one personal account and has no recorded backup administrator or independent approving reviewer.

The dated continuity, recovery, emergency-release and access-removal policy is [`repository-continuity.md`](repository-continuity.md). Its current machine-readable state is `pending_external_admin_acceptance`. That state must remain pending until a shared ownership model, protected `main` ruleset, backup administrator, independent reviewer and private acceptance evidence are all established by authorized humans.

As of August 3, 2026, branch hygiene is complete and the repository branch inventory is `main` only. This removes historical branch-ref risk but does not satisfy organization ownership or protected-review requirements.

## What this verification proves

This record verifies control and representation for the GitHub repository and artifacts produced by its workflows. It supports code provenance, review routing, security intake, support triage, and release attribution.

## What this verification does not prove

Repository ownership is not a substitute for legal-entity verification, government identity checks, trademark ownership, bank or payment verification, domain ownership, Shopify Partner-account ownership, Shopify App Store identity review, WordPress-site ownership, client authorization, or contractual authority over an external system.

It also does not prove shared administrative continuity, independent review, branch-protection enforcement or administrator-bypass resistance. Those controls require GitHub administration and acceptance evidence outside source code.

Those external checks must be completed by the real owner or an authorized human representative on the relevant platform. Sensitive evidence must remain in an approved private system rather than this public repository.

## External owner-representative acceptance record

For each live domain, store, deployment, or pilot, record the following outside the public repository:

- legal or operating entity;
- representative name and role;
- system, domain, or store being authorized;
- basis of authority;
- approved read/write scope;
- authorization date and expiry, if any;
- private evidence location;
- revocation contact and procedure;
- acceptance result and any restrictions.

Only a non-sensitive reference or completion status should be copied into the relevant GitHub issue.
