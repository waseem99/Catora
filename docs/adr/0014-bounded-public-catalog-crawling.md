# ADR 0014: Bounded public catalog crawling

## Status

Accepted

## Context

Catora needs a credential-free diagnostic path for prospects that cannot yet provide Shopify or catalog exports. Public catalog analysis creates security, legal, reliability, and scope risks if implemented as an unrestricted crawler.

## Decision

- Require an explicit confirmation that the workspace is authorized to analyze the target domain.
- Accept either one HTTPS sitemap entry point or an explicit bounded list of HTTPS product URLs.
- Restrict every discovered URL and redirect to the exact seed hostname.
- Reject credentials, custom ports, fragments, non-HTTPS URLs, and hosts resolving to non-public IP addresses.
- Revalidate redirects and DNS results before requests.
- Respect `robots.txt`; a missing file permits crawling, while retrieval or policy errors fail closed.
- Apply the greater of the configured crawl delay and a supported robots crawl delay.
- Limit products, sitemap documents, redirects, and response sizes.
- Prefer Schema.org `Product` JSON-LD and retain a deterministic HTML metadata/text fallback.
- Store immutable source snapshots and deterministic hashes through the existing ingestion lifecycle.
- Reject pages without product evidence instead of treating every sitemap URL as a product.
- Do not execute page JavaScript, bypass access controls, authenticate, or crawl across hosts.

## Consequences

The connector is suitable for targeted sales diagnostics and initial pilots, not broad web scraping. Sites that require client-side rendering may provide reduced fallback data and should use CSV or Shopify ingestion for higher fidelity. DNS validation reduces SSRF exposure, while production deployments should additionally apply network-level egress controls.
