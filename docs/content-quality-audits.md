# Deterministic catalog content-quality audits

Catora creates two immutable built-in rules for every immutable taxonomy category and version:

- `builtin.<category>.title_quality`
- `builtin.<category>.description_quality`

The rules use the existing versioned rule tables and are selected into the audit run's immutable `rule_version_set`. They require no LLM call and cannot change after an audit begins.

## Title quality

The first algorithm version checks a normalized product title for:

- missing content;
- fewer than 8 or more than 180 characters;
- titles composed only of generic catalog terms;
- all-capital text;
- a token repeated more than twice.

A failed title rule contributes to discoverability readiness and produces a `rewrite_title` remediation.

## Description quality

Descriptions are checked for:

- missing content;
- fewer than 60 or more than 5,000 characters;
- fewer than 3,000 basis points of unique lexical tokens;
- exact reuse of the normalized product title.

A failed description rule contributes to discoverability readiness, carries conversion impact, and produces a `rewrite_description` remediation.

## Evidence and reproducibility

The normalized product title is inserted into the product audit snapshot as a normal string attribute. Product-level provenance references are attached to it as evidence. Description evidence already comes from the normalized attribute pipeline.

Because title and its evidence are part of the existing canonical snapshot serialization, changing a title changes the product snapshot hash and is detected by incremental audit selection. Finding fingerprints contain the immutable rule-version ID, product, field, check, and sorted failure codes; the text value itself is intentionally excluded so a continuing quality failure remains the same finding.

When these built-in rule versions are first introduced for an existing taxonomy version, the rule-version set changes. The next audit must be full; later incremental runs require the same unchanged rule-version set as their baseline.
