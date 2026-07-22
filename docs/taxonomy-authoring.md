# Taxonomy authoring guide

Catora taxonomies are immutable, versioned JSON packages validated by the Pydantic contract in `catora_api.taxonomy.schema` and the checked-in JSON Schema beside the bundled package.

## Versioning

- Published packages use semantic versions such as `1.0.0`.
- Never edit a published version in place. Copy it, increment the version, and make the change in the new package.
- Compilation records a SHA-256 fingerprint in every taxonomy field and rule version. Recompiling identical content is idempotent; different content under an existing version is rejected.

## Categories and inheritance

A category may name one `parent_key`. Requirements resolve in this order:

1. the field's `default_requirement`;
2. inherited parent requirements, from root to nearest parent;
3. the category's own requirement overrides.

Non-assignable parent categories hold shared rules without becoming selectable primary categories. Assignable categories require deterministic classification signals. Ties and zero-signal products remain ambiguous or unclassified; the classifier never forces a category.

## Fields

Every field defines:

- canonical key and display label;
- data type and product/variant scope;
- canonical and accepted units or enumerated values;
- default and category-specific requirement level;
- market and locale applicability;
- validation constraints;
- acceptable evidence paths and approval needs;
- supported buyer intents;
- Schema.org/SEO mapping;
- whether a human must verify the value.

Use `required` only when the field materially affects safe purchase, fit, compatibility, or core product discovery. Use `recommended` for fields that strongly improve comparison or confidence. `optional` fields are retained but do not compile into presence rules. `not_applicable` must be explicit when a shared field does not apply.

## Adding a category

1. Add a new category with a unique canonical key.
2. Prefer inheritance from an existing non-assignable parent.
3. Add precise signals that do not overlap unnecessarily with sibling categories.
4. Override only requirements that differ from the parent.
5. Add representative mapping fixtures, including an ambiguity case when signals overlap.
6. Run the API tests. Invalid references, cycles, duplicate keys, stale JSON Schema, or failed fixtures stop CI.

## Adding a new vertical

Create a new package using the same schema and compiler. Core audit code consumes compiled categories, taxonomy fields, and rule versions; it must not contain furniture-specific branching.

## Examples

Valid measurement field:

```json
{
  "key": "width_mm",
  "label": "Width",
  "data_type": "decimal",
  "scope": "product",
  "canonical_unit": "mm",
  "allowed_units": ["mm", "cm", "m", "in"],
  "constraints": {"minimum": 1, "maximum": 20000}
}
```

Invalid examples include an enum without `allowed_values`, a canonical unit absent from `allowed_units`, a category referencing an unknown field, or an inheritance cycle.
