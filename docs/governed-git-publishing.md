# Governed Git and Next.js publishing

Catora converts approved, evidence-backed recommendations into draft pull requests. It does not
push to a protected branch, merge, deploy, or publish production content.

## Connection contract

A repository connection is tenant scoped and records:

- provider and repository identity;
- protected default branch;
- explicit path allowlist;
- protected branch list;
- a managed credential reference, never a token value;
- a tested provider capability snapshot.

The production provider contract prohibits merge and deploy capabilities. GitLab and Bitbucket are
represented by the provider-neutral contract but remain unavailable until an accepted adapter is
implemented and tested. The first concrete adapter targets GitHub's Git data and pull-request APIs.

## Proposal lifecycle

1. An authorized user creates a deterministic draft proposal from approved evidence.
2. Each file item declares `create` or `update`, content hash, expected current blob SHA for updates,
   and exact evidence references.
3. The path policy rejects traversal, workflow/infrastructure/secret files, non-allowlisted paths,
   secret-like content, duplicate targets, and protected branches.
4. The manifest records the reviewed base revision, patch hash, rollback plan, branch, title, body,
   evidence, and idempotency key.
5. An owner or admin approves the exact patch hash.
6. Submission re-reads the protected branch and every target blob. Any newer revision or changed
   target produces an explicit conflict instead of overwriting it.
7. The provider creates blobs, a tree, one proposal commit, a proposal branch, and a **draft** pull
   request. The adapter has no merge or deployment method.
8. External reviewers decide whether to edit, close, merge, deploy, or revert the proposal.
9. Post-publish validation can only be recorded after an authorized operator supplies the published
   revision and validation evidence.

## Supported proposal scope

The allowlist can cover Next.js content and SEO implementation paths such as:

- location, city, service-area, menu, menu-item, and FAQ content;
- titles, descriptions, headings, structured data, canonicals, redirects, sitemaps, internal links,
  and image alt text;
- bounded data/content modules used by approved routes.

The default policy rejects `.env` files, dependency lockfiles, deployment configuration,
infrastructure directories, GitHub Actions workflows, secrets, and arbitrary repository-wide code.

## Security and failure isolation

- Credentials use an `env:` reference in the first runtime resolver and never enter API responses,
  patches, logs, audit payloads, or provider error messages.
- Repository, workspace, base revision, branch, path, expected blob, evidence, and idempotency are
  validated before any provider write.
- Provider errors are sanitized. Failed submissions retain a conflict record and never alter the
  protected branch.
- Disconnect revokes the credential reference and stops new proposals without deleting immutable
  proposal, reviewer, evidence, patch, and audit history.
- Catora availability has no effect on the restaurant website or deployment pipeline.

## Runtime gate

Live submission requires `CATORA_GIT_PUBLISHING_ENABLED=true`. Draft creation and review can remain
available while provider submission is disabled.

Ranchers repository access and production proposals remain gated by issue #222 and require the
repository owner, SEO/content reviewer, security review, and external merge/deployment owner.
