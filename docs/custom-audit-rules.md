# Custom relational audit rules

Workspace owners and administrators can add deterministic relationship checks without uploading or executing code.

## API

`POST /api/v1/workspaces/{workspace_id}/audit-rules` creates an immutable rule version. `GET` on the same path lists the workspace's custom rules. There are deliberately no update, patch, or delete endpoints.

A request supplies a canonical rule key, taxonomy version, category, current field, related field, severity, and one relationship operator:

- `less_than_or_equal_to_field`
- `greater_than_or_equal_to_field`
- `matches_product_field`

The server resolves both fields from immutable taxonomy records. It rejects unknown fields, incompatible scopes or types, mismatched canonical units, numeric self-references, and product-only fields used for product-versus-variant matching. Request bodies forbid additional properties, so scripts, expressions, callbacks, and arbitrary executable payloads are not accepted.

## Versioning and execution

Definitions use the reserved `custom.` key namespace. A definition may receive one immutable version per taxonomy version, but an existing version cannot be overwritten. Changing or removing a rule requires a new taxonomy/rule version rather than mutating historical audit inputs.

Full audit creation snapshots compiled taxonomy rules and custom relationship rules together. Incremental runs require exactly the same rule-version set as their baseline; after a custom rule is added, the next run must therefore be full. This preserves reproducibility and makes score changes attributable to an explicit rule-version-set change.

Custom rules contribute only a `cross_field_consistency` evaluation. They do not duplicate the taxonomy rule's presence, type, format, range, unit, structured-data, or discoverability contributions. Missing related evidence yields `not_evaluated`, while deterministic inconsistencies create evidence-backed findings with stable fingerprints.

## Authorization and auditability

Any workspace member may list rules. Creation requires the existing owner/admin taxonomy-management capability and CSRF protection. Successful creation writes an append-only audit event containing the rule key, version, fields, relationship, and severity.
