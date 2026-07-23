# Prospect-specific catalog diagnostics

Catora supports a low-friction sales and qualification path for merchants who are not ready to install a Shopify app. An authorized operator can upload the merchant's standard Shopify products CSV and receive an isolated, evidence-backed assessment.

## Operator journey

1. Open a Catora workspace and choose **Bring in a catalog**.
2. Select **Upload Shopify CSV**.
3. Enter the prospect company, market, locale, currency, retention window and optional Shopify domain.
4. Confirm that the prospect authorized the diagnostic and retention window.
5. Upload Shopify's all-products export.
6. Follow the persisted assessment stages until completion.
7. Download the editable executive PPTX and operational remediation CSV.

## Persisted stages

The UI reports only stages proven by persisted records:

- queued;
- importing catalog;
- normalizing products and variants;
- assigning furniture taxonomy;
- running the deterministic audit;
- testing prepared buyer intents;
- preparing branded deliverables;
- complete.

Catora does not invent percentage progress when the total work is unknown. If a transient API request fails, the browser keeps the last verified assessment state and labels it accordingly.

## Data boundaries

Each diagnostic creates a separate organization and workspace. Owner or admin capability is required to create, upload, delete or purge the assessment. The operator receives a scoped membership in the prospect workspace.

Browser resume state contains only the assessment and workspace identifiers. It never contains catalog rows, credentials or tokens.

Rejected row responses are deliberately bounded and expose only:

- row number;
- rejection reason;
- product handle, when available;
- variant SKU, when available.

The original row payload remains private server-side evidence.

## Retention and deletion

The operator chooses a retention window between 1 and 90 days. The expiry timestamp and authorization confirmation are stored with the assessment.

The protected delete action removes:

- the private uploaded CSV;
- the prospect organization and workspace;
- source records, products, variants and evidence;
- audit findings and intent results;
- the assessment state.

The deletion audit event is recorded on the surviving operator workspace. Owners and admins can also run the bounded expired-diagnostic purge endpoint.

## Deliverables

Completed assessments expose:

- an editable six-slide prospect-branded PPTX;
- a finding-level operational CSV;
- the imported product browser;
- reconciled catalog, taxonomy, finding and buyer-intent counts;
- a bounded rejection report.

Both downloadable artifacts are generated from the same persisted audit findings and buyer-intent results shown in the application.

## Deliberate limitations

This workflow is a one-time catalog diagnostic. It does not install a Shopify app, persist a merchant access token, receive webhooks or write changes back to a storefront. Those continuous-pilot capabilities are tracked separately in #124 and #125.
