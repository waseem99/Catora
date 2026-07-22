# Built-in buyer-intent templates

Catora ships a versioned, immutable starter library for common furniture and home-product buying
questions. The templates are deterministic application data: listing or reading them never calls an
AI provider, writes to the database, approves an intent, or executes catalog matching.

The initial `1.0.0` library covers compact spaces, family seating, easy-care dining, weather-ready
outdoor seating, accessible adjustable workspaces, low-assembly storage, and constrained apartment
delivery. Every category and field key is validated against the bundled published furniture/home
taxonomy `1.0.0` when the module loads, and every template is validated through
`StructuredBuyerIntent`.

Workspace members can list and filter templates through:

- `GET /api/v1/workspaces/{workspace_id}/buyer-intent-templates`
- `GET /api/v1/workspaces/{workspace_id}/buyer-intent-templates/{template_key}`

Supported collection filters are `category_key`, `use_case`, `offset`, and `limit`. Ordering is
stable by template key and the returned total is computed from the same filtered in-memory set used
for pagination.

Users with buyer-intent authoring permission can create an editable draft directly from one exact
template version through:

- `POST /api/v1/workspaces/{workspace_id}/buyer-intent-templates/{template_key}/materialize`

The request includes `expected_template_version` and an optional draft-name override. A version
mismatch fails with a conflict instead of silently materializing different template content. The
response identifies the template key, template version, taxonomy version, and created buyer intent.

Materialization creates a normal version-1 buyer-intent record with `source=template` and
`approval_status=draft`. The audit event `intent.created_from_template` persists the template key,
template version, taxonomy version, lineage, and created intent version. Materialization never
approves or executes the draft, and it never calls an AI provider. All later edits, approval, suite
membership, execution, and analytics use the same boundaries as any other buyer intent.
