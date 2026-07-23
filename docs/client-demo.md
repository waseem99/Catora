# Catora client-winning demo

This is the authoritative presenter flow for the prepared `sales-demo` workspace. It uses persisted Catora products, evidence, audit findings, buyer-intent matches, recommendations, review decisions and change sets. The screen does not use screenshots or invented client-side totals.

## Prepare the environment

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
npm run demo:seed
```

Set `CATORA_DEMO_PASSWORD` before the seed command to choose a password. When it is absent, the command generates a password and prints it once. The login is always `demo@catora.local`.

The seed command deletes and recreates only the `sales-demo` workspace. Other organizations and workspaces are untouched. The enterprise showcase contains 1,000 products, 2,000 active variants/SKUs, ten categories and five prepared buyer-intent scenarios.

## Presenter preflight

Owners and admins see a **Demo readiness** panel above the guided route. Run it before every client meeting.

The preflight checks:

- the enterprise-scale persisted demo data;
- PostgreSQL queryability;
- Redis connectivity;
- private object-storage bucket access;
- Celery worker response;
- editable PPTX generation.

The panel also shows the timestamp and counts from the latest completed audit snapshot. If a live dependency is temporarily unavailable, Catora labels the state as **Using verified fallback** and continues to show the persisted, timestamped analysis. It does not claim that an unavailable live synchronization succeeded.

## Presenter route

1. Sign in at `http://localhost:3000/login` or the hosted application domain.
2. Select **Northstar Living — Sales Demo**.
3. Choose **Launch client demo**.
4. Confirm the presenter readiness panel.
5. Complete the five sections in order.

### 1. Catalog overview

Explain that catalog health and confidence are deterministic, persisted audit metrics. Highlight product/variant scale, high-value findings and the most common missing attributes.

### 2. Evidence-backed defect

Open **Cloudline Compact Three-Seat Sofa**. Show that width is absent from the source export and that Catora retains the source path and excerpt rather than guessing.

### 3. Buyer-intent impact

Use the prepared query: “Which three-seat sofas fit a compact apartment and are easy to care for?” The hero product is relevant but remains `possible_match_missing_data` because width cannot be proven.

### 4. Controlled recommendation decision

- Verify and approve the proposed `width_mm` value.
- Approve the source-supported care instructions.
- Reject the unsupported warranty proposal.
- Create the approved change set.

The application blocks factual approval without verification and blocks every decision when the current product no longer matches the recommendation snapshot. The post-change buyer-intent result is explicitly labelled as a projection; nothing is published automatically.

### 5. Forwardable proof

Download:

- the editable six-slide executive assessment PPTX;
- the operational remediation backlog CSV.

Both are generated from the same persisted records shown by the guided route. Downloads create audit events.

## Reset before another presentation

An owner or admin can choose **Reset demo workspace** in the presenter panel. The API records the attributable request before enqueueing the exact Celery task identity, then recreates only the deterministic `sales-demo` workspace. The panel only polls task IDs recorded for that workspace and reloads the completed demo.

The command-line fallback remains:

```bash
npm run demo:seed
```

Use the newly printed password when `CATORA_DEMO_PASSWORD` is not set.

## Failure fallback

- Run the presenter preflight and read the component-specific status.
- Confirm API readiness at `http://localhost:8000/health/ready`.
- Apply migrations with `docker compose exec api alembic upgrade head`.
- Reset the workspace through the presenter panel or `npm run demo:seed`.
- Confirm the browser API URL is `http://localhost:8000` for local Docker Compose.
- For hosted environments, run `npm run demo:smoke` with the documented smoke-test variables.

A failed reset returns a sanitized failure state and keeps the previous verified snapshot available. Task failures never expose subprocess output, credentials or raw catalog records to the browser.

## Scope boundaries

The demo proves catalog intelligence, evidence, buyer-intent coverage, controlled review and executive reporting. It does not claim autonomous storefront publishing, guaranteed search ranking or revenue attribution.
