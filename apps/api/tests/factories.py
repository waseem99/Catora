from __future__ import annotations

import uuid

from catora_api.db.models import Organization, Product, Workspace


def organization_factory(**overrides: object) -> Organization:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Demo Commerce Group",
        "slug": f"demo-{uuid.uuid4().hex[:8]}",
    }
    values.update(overrides)
    return Organization(**values)


def workspace_factory(organization_id: uuid.UUID | None = None, **overrides: object) -> Workspace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": organization_id or uuid.uuid4(),
        "name": "Furniture Pilot",
        "slug": f"furniture-{uuid.uuid4().hex[:8]}",
    }
    values.update(overrides)
    return Workspace(**values)


def product_factory(workspace_id: uuid.UUID | None = None, **overrides: object) -> Product:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "workspace_id": workspace_id or uuid.uuid4(),
        "canonical_key": f"product-{uuid.uuid4().hex}",
        "title": "Three-seat sofa",
        "status": "active",
    }
    values.update(overrides)
    return Product(**values)
