# Shopify public app release and review runbook

This is the release-control companion to `docs/shopify-public-acceptance.md`. It covers the repository-controlled work required after development-store deployment and before production App Store submission. It does not claim that Shopify registrations, live acceptance, screenshots, or review approval are complete.

## Release objective

Publish **Catora Catalog Intelligence** as a public Shopify app with **Limited visibility**. The app remains invite-only through Catora's server-side store invitation boundary. The Limited-visibility listing URL is a distribution mechanism, not an authorization control.

The existing Northstar custom-distribution app remains the private demonstration and one-merchant pilot route. Do not replace its registration, credentials, callback, installation, or encryption key while preparing the public app.

## Final listing copy

### App name

Catora Catalog Intelligence

### App card subtitle

Audit catalog quality and buyer-intent readiness

### Concise value proposition

Audit product catalog quality, identify missing or ambiguous product data, test buyer-intent discoverability, and download evidence-backed remediation reports.

### Listing description

Catora analyzes your Shopify product catalog and turns catalog-quality gaps into a prioritized remediation plan.

After an approved store installs the app, Catora securely synchronizes products, variants, options, media, collections, metafields, and SEO fields using read-only Shopify access. It then runs deterministic catalog audits and buyer-intent tests to show where product data is complete, ambiguous, missing, or difficult to discover.

Inside Shopify Admin, merchants can monitor synchronization, review catalog-health findings, inspect buyer-intent results, and download an editable presentation and remediation CSV. Catora does not access customers, orders, payments, or checkout data. It does not publish changes back to Shopify in this release.

### Scope explanation

`read_products` is required to synchronize product and variant catalog data for catalog-quality analysis. The reviewed release requests no write scopes and no customer, order, payment, or checkout scopes.

### Honest limitations

- Recommendations are based on synchronized catalog evidence and deterministic rules.
- Catora does not guarantee rankings, traffic, conversion, or revenue outcomes.
- The reviewed release is read-only and does not publish product changes.
- Shopify Plus markets, B2B catalogs, contextual pricing, and controlled write-back are outside the first release.

## Screenshot plan

Capture screenshots only from the deployed production-registration review store after the full acceptance record passes. Do not include access tokens, store secrets, internal IDs, test emails, browser developer tools, terminal windows, fabricated results, reviews, testimonials, pricing claims, URLs, or unsupported statistics.

Required sequence:

1. Invitation accepted and embedded welcome state.
2. Initial synchronization progress with real store counts.
3. Completed catalog-health overview.
4. Evidence-backed finding detail.
5. Buyer-intent analysis summary.
6. Report and remediation-download controls.
7. Reauthorization or recovery state, only if it is clean and intentional.

Use consistent browser dimensions and Shopify Admin chrome. The screenshots must show a functional embedded experience rather than a redirect-only shell.

## Reviewer walkthrough

Before submission, create a production-registration review store invitation and record its values in an uncommitted `shopify/public/review-submission.json` file based on the example file.

Reviewer instructions:

1. Open the supplied Shopify App Store installation URL while signed into the supplied review development store.
2. Install the app and grant the single requested `read_products` scope.
3. Open **Catora Catalog Intelligence** from Shopify Admin.
4. Confirm the invitation is recognized and activate the app.
5. Wait for the initial synchronization and analysis to complete. The App Home should show the store's real product and variant counts.
6. Open the findings and buyer-intent sections.
7. Download the editable PPTX report and remediation CSV.
8. Change one non-sensitive product field in Shopify Admin, return to Catora, and confirm a new verified synchronization and analysis timestamp.
9. Uninstall the app and confirm Catora disconnects without affecting the Northstar custom-distribution installation.

The reviewer must not need a Catora engineer to enter a token, run a console command, repair data, or change a database row.

## Production registration checklist

Do not start this checklist until the development-registration acceptance record is complete on the required separate stores.

- Create `Catora Shopify — Production` as a public-distribution app.
- Link `shopify/public/shopify.app.production.toml.example` with Shopify CLI without committing the generated client ID.
- Set the production public client ID in the `apps/shopify` Vercel project.
- Set the production public client ID, client secret, canonical App Home URL, exact scope list, production registration label, and separate credential-encryption key on Railway.
- Deploy API, worker, App Home, and production Shopify configuration.
- Create the review-store invitation before the reviewer installs the app.
- Run the complete hosted acceptance flow against the production registration.
- Capture final screenshots only after acceptance passes.
- Complete all fields in the App Store review page and run Shopify's automated preliminary checks.
- Select Limited visibility before publication.
- Record the approved direct listing URL in the operator runbook and sales workflow without treating it as an authorization secret.

## Release gate

Submission is blocked until all items below are true:

- Development acceptance passes on at least three separate stores.
- Production-registration preflight passes.
- The reviewer store can install, activate, synchronize, analyze, download reports, process a product change, and uninstall without developer intervention.
- Exact `read_products` scope enforcement passes.
- Mandatory compliance webhooks pass with valid HMAC and reject invalid HMAC.
- Reauthorization, uninstall, and `shop/redact` acceptance pass on disposable stores.
- Northstar custom-distribution validation remains green.
- Support, privacy, terms, and review-contact fields contain authoritative values.
- Screenshots contain no placeholders, secrets, testimonials, pricing claims, URLs, or fabricated results.
- `python scripts/validate_shopify_public_release.py --metadata shopify/public/review-submission.json` passes.

## Rollback procedure

### Before Shopify submission

- Disable new invitations.
- Keep existing installations readable and uninstall/compliance handling active.
- Roll back the App Home deployment in Vercel to the last accepted deployment.
- Roll back API and worker in Railway to the last accepted image.
- Re-run deployment preflight and existing-installation status checks.

### After submission but before approval

- Withdraw the submission in the Shopify review page if a release blocker is found.
- Do not change the production registration to a different code path while review is active.
- Apply the fix through the normal pull-request and validation gates.
- Re-run the reviewer walkthrough from a fresh Shopify Admin session before resubmitting.

### After approval

- If a severe regression affects activation, pause new invitations and new activations while preserving existing data, status, compliance, and uninstall handling.
- Roll back Vercel, API, and worker to the last accepted release as one coordinated version.
- Confirm compliance webhooks and uninstall remain reachable after rollback.
- Record the incident, affected registration, deployment versions, shops, bounded failure stage, and recovery result without tokens or raw catalog payloads.

Shopify configuration rollback must use a known source-controlled app configuration version. Never repair an app version by editing secrets or scopes ad hoc in production.

## Merchant support runbook

Support must never ask a merchant to send an access token, refresh token, app secret, HMAC signature, session token, webhook body, or private catalog export.

Request only:

- permanent `*.myshopify.com` domain;
- approximate time of the problem;
- visible App Home status and bounded error text;
- whether the issue occurred during installation, activation, synchronization, analysis, report download, reauthorization, or uninstall;
- a screenshot with customer data, secrets, browser storage, developer tools, and unrelated tabs removed.

Operator response sequence:

1. Confirm the app registration and deployment environment for the installation.
2. Check invitation, installation, scope, sync, retry/dead-letter, webhook, reconciliation, analysis, and report status through the bounded operator APIs.
3. Use the idempotent recovery action only when the installation reports recovery is required.
4. Ask the merchant to reauthorize only when exact-scope or refresh-token state requires it.
5. Escalate with sanitized correlation data and bounded failure type. Do not query or paste encrypted credential fields.
6. For uninstall or deletion questions, verify revocation and deletion receipts without restoring deleted merchant data.

## API-version calendar

The source-controlled version policy is `shopify/public/api-version-policy.json`.

- Run a compatibility review by the recorded review date.
- Test the recorded upgrade target against development stores and the release-candidate contract.
- Complete the upgrade by the internal deadline, before the support-end guardrail.
- Update GraphQL endpoints, webhook versions, both TOML templates, contract validation, tests, acceptance evidence, and this policy in the same release train.
- Query Shopify's supported API versions during the operator review and attach sanitized evidence to the release record.

## Required operator metadata

Copy `shopify/public/review-submission.example.json` to the ignored file `shopify/public/review-submission.json` and fill every blank field with authoritative information. Do not commit review-store contact details or internal release notes unless they are intentionally public.

<!-- Branch-only CI maintenance verification marker; do not merge. -->
