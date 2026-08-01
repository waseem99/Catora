# Restaurant technical and on-page audit rules

`restaurant-web-audit/v1` composes restaurant page observations with Catora's existing immutable
`TaxonomyFieldRule`, `ProductAuditSnapshot`, `RuleEvaluation`, `FindingCandidate`, fingerprint,
severity-weight, and evidence contracts. It does not create a second audit persistence or scoring
engine.

## Supported page identities

The first rule pack accepts explicit page identities for:

- brand pages;
- branch/location pages;
- service-area pages;
- menu pages;
- menu-item pages.

Each page uses a stable UUID supplied by the source/orchestration layer. Ambiguous page or branch
identity must be resolved before evaluation; this pack does not guess an entity from prose.

## Base immutable rules

Every page receives deterministic rules for:

- URL and successful HTTP status;
- canonical URL;
- title, meta description, and primary heading;
- visible body-content depth;
- structured-data inventory;
- internal-link count;
- response time.

These rules use the existing presence, type, length, range, URL, discoverability, fingerprint, and
score-contribution behavior.

## Restaurant-specific checks

The pack adds deterministic evaluations using the same `RuleEvaluation` and `FindingCandidate`
contracts:

- indexability, robots permission, and sitemap inclusion;
- self-canonical consistency after conservative URL normalization;
- required Schema.org type by page identity;
- raw-versus-rendered content visibility;
- thin branch/service-area/menu content;
- volatile restaurant-fact freshness;
- obvious WAF, CAPTCHA, or bot-access blocking diagnostics.

All findings retain source evidence and stable fingerprints. Repeated execution with the same
inputs and audit time produces identical evaluations.

## Evidence and stop conditions

The evaluator consumes persisted, authorized observations. It does not crawl private pages, bypass
access controls, execute arbitrary JavaScript, call PageSpeed/CrUX, or infer restaurant facts.

Evaluation must stop before this layer when page identity, source authorization, tenant scope, or
evidence provenance is unknown. Missing or inaccessible observations are explicit; they are never
converted into confident pass states.

## Performance measurements

The first version accepts an observed response time as evidence and keeps that measurement separate
from browser lab data or field data. PageSpeed Insights and CrUX connectors remain external work
under the measurement roadmap. No Core Web Vitals, ranking, traffic, citation, or revenue guarantee
is produced.

## Rollout and rollback

Use synthetic fixtures and shadow evaluations first. A later orchestration slice may persist these
results through the existing `AuditRun` lifecycle after workspace policy enables the restaurant
module. Rollback selects the prior immutable rule-pack version and retains historical findings.

Ranchers production evaluation remains gated by issue #222.
