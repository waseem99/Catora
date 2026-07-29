# Catora Service Visibility Intelligence

Catora Service Visibility Intelligence audits authorized WordPress service websites for technical SEO, answer readiness, and AI-discovery evidence. It extends Catora's existing bounded public-site ingestion, immutable evidence, reporting, and approval controls rather than creating a separate crawler.

## Supported onboarding

- **Zero-install audit:** Catora crawls an authorized HTTPS WordPress sitemap and public pages while enforcing robots.txt, exact-host boundaries, public-IP resolution, response-size limits, pacing, and resumable ingestion.
- **WordPress bridge:** the optional plugin sends signed snapshots containing only published public content and public SEO metadata. It does not send users, forms, customers, orders, members, private posts, password-protected posts, or unpublished drafts.

## Outputs

Each completed run produces an evidence JSON file, findings CSV, 25-question buyer-coverage CSV, Markdown remediation brief, and editable PPTX. Findings link to public-page evidence and are marked new or persisting; later runs also count resolved findings.

## Product claims

Catora measures readiness and prepares evidence-backed recommendations. It does not guarantee rankings, traffic, leads, revenue, rich results, or citations by AI systems.

## Publishing boundary

Automatic publishing is not supported. Draft delivery is disabled by default. When enabled and explicitly approved in Catora, the plugin creates a separate unpublished WordPress draft and refuses stale base revisions. It does not rewrite Elementor structures or replace a live page.

## Repository release gate

Run:

```bash
npm run service-visibility:release-check
npm run service-visibility:plugin
```

The dedicated GitHub workflow additionally validates migration `0019`, Ruff, strict MyPy, focused API tests, PHP syntax, plugin packaging, web lint/type-check/tests/build, safe defaults, and a 90-day installable plugin artifact.

## External pilot gate

Repository completion does not replace real-site authorization. Issue #203 requires one authorized zero-install pilot and one authorized plugin-assisted pilot, owner review of findings, a small approved remediation set, a repeat scan, and a commercial proceed/change/stop decision.
