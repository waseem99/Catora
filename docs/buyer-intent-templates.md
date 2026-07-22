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

A template becomes editable only when a user explicitly submits its `name` and `structured_intent`
to the existing buyer-intent create endpoint with `source` set to `template`. The resulting workspace
record starts as a draft and follows the same versioning, approval, and execution boundaries as any
other buyer intent.
