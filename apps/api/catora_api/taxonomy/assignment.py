from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import Category, Product, ProductAttribute
from catora_api.db.models.taxonomy import ProductCategoryTag
from catora_api.taxonomy.compiler import TaxonomyCompiler, TaxonomyCompileSummary
from catora_api.taxonomy.loader import load_bundled_taxonomy
from catora_api.taxonomy.resolution import ClassificationResult, classify_product
from catora_api.taxonomy.schema import TaxonomyPackage

CATEGORY_CLASSIFIER_VERSION = "taxonomy-signal-v1"
_PREVIEW_ATTRIBUTE_KEYS = frozenset({"description", "category", "product_type", "collections"})


class TaxonomyProductNotFoundError(LookupError):
    pass


class TaxonomyCategoryNotFoundError(LookupError):
    pass


class TaxonomyAssignmentConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProductCategoryAssignment:
    product: Product
    primary_category: Category
    secondary_categories: tuple[Category, ...]


class TaxonomyAssignmentService:
    def __init__(self, package: TaxonomyPackage | None = None) -> None:
        self.package = package or load_bundled_taxonomy()
        self._compiler = TaxonomyCompiler()
        self._definitions = {category.key: category for category in self.package.categories}

    async def compile_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
    ) -> TaxonomyCompileSummary:
        return await self._compiler.compile(
            session,
            workspace_id=workspace_id,
            package=self.package,
        )

    async def preview_product(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> tuple[Product, ClassificationResult]:
        product = await self._product(session, workspace_id=workspace_id, product_id=product_id)
        attributes = (
            await session.scalars(
                select(ProductAttribute).where(
                    ProductAttribute.workspace_id == workspace_id,
                    ProductAttribute.product_id == product_id,
                    ProductAttribute.variant_id.is_(None),
                    ProductAttribute.key.in_(sorted(_PREVIEW_ATTRIBUTE_KEYS)),
                    ProductAttribute.value_state == "present",
                )
            )
        ).all()
        values = {attribute.key: attribute.value for attribute in attributes}
        category_text = " ".join(
            text
            for key in ("category", "product_type", "collections")
            if (text := _text_value(values.get(key)))
        )
        result = classify_product(
            self.package,
            title=product.title,
            category_text=category_text or None,
            description=_text_value(values.get("description")),
        )
        return product, result

    async def assignment(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> ProductCategoryAssignment:
        product = await self._product(session, workspace_id=workspace_id, product_id=product_id)
        if product.primary_category_id is None:
            raise TaxonomyCategoryNotFoundError("Product has no primary category assignment")
        primary = await session.scalar(
            select(Category).where(
                Category.workspace_id == workspace_id,
                Category.id == product.primary_category_id,
            )
        )
        if primary is None:
            raise TaxonomyCategoryNotFoundError("Primary category assignment is unavailable")
        tags = (
            await session.scalars(
                select(ProductCategoryTag).where(
                    ProductCategoryTag.workspace_id == workspace_id,
                    ProductCategoryTag.product_id == product_id,
                    ProductCategoryTag.taxonomy_version == primary.taxonomy_version,
                )
            )
        ).all()
        category_ids = [tag.category_id for tag in tags]
        secondary: tuple[Category, ...] = ()
        if category_ids:
            categories = (
                await session.scalars(
                    select(Category).where(
                        Category.workspace_id == workspace_id,
                        Category.id.in_(category_ids),
                    )
                )
            ).all()
            secondary = tuple(sorted(categories, key=lambda category: category.key))
        return ProductCategoryAssignment(product, primary, secondary)

    async def assign(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
        taxonomy_version: str,
        primary_category_key: str,
        secondary_category_keys: list[str],
        actor_user_id: uuid.UUID,
        reason: str,
    ) -> ProductCategoryAssignment:
        if taxonomy_version != self.package.version:
            raise TaxonomyAssignmentConflictError(
                "Unsupported taxonomy version "
                f"{taxonomy_version!r}; expected {self.package.version!r}"
            )
        if primary_category_key in secondary_category_keys:
            raise TaxonomyAssignmentConflictError(
                "Primary category cannot also be assigned as a secondary category"
            )
        if len(secondary_category_keys) != len(set(secondary_category_keys)):
            raise TaxonomyAssignmentConflictError("Secondary category keys must be unique")

        product = await self._product(session, workspace_id=workspace_id, product_id=product_id)
        primary_definition = self._definitions.get(primary_category_key)
        if primary_definition is None or not primary_definition.assignable_primary:
            raise TaxonomyCategoryNotFoundError(
                f"Unknown assignable primary category {primary_category_key!r}"
            )
        for key in secondary_category_keys:
            definition = self._definitions.get(key)
            if definition is None or not definition.allow_secondary_tag:
                raise TaxonomyCategoryNotFoundError(f"Unknown secondary category {key!r}")

        requested_keys = {primary_category_key, *secondary_category_keys}
        categories = (
            await session.scalars(
                select(Category).where(
                    Category.workspace_id == workspace_id,
                    Category.taxonomy_version == taxonomy_version,
                    Category.key.in_(sorted(requested_keys)),
                    Category.is_immutable.is_(True),
                )
            )
        ).all()
        by_key = {category.key: category for category in categories}
        missing = requested_keys - set(by_key)
        if missing:
            raise TaxonomyAssignmentConflictError(
                "Taxonomy is not compiled for this workspace or is incomplete: "
                + ", ".join(sorted(missing))
            )

        primary = by_key[primary_category_key]
        product.primary_category_id = primary.id
        await session.execute(
            delete(ProductCategoryTag).where(
                ProductCategoryTag.workspace_id == workspace_id,
                ProductCategoryTag.product_id == product_id,
            )
        )
        for key in secondary_category_keys:
            session.add(
                ProductCategoryTag(
                    workspace_id=workspace_id,
                    product_id=product_id,
                    category_id=by_key[key].id,
                    assigned_by_user_id=actor_user_id,
                    taxonomy_version=taxonomy_version,
                    assignment_source="manual",
                    reason=reason,
                )
            )
        await session.flush()
        secondary = tuple(by_key[key] for key in sorted(secondary_category_keys))
        return ProductCategoryAssignment(product, primary, secondary)

    async def _product(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> Product:
        product = await session.scalar(
            select(Product).where(
                Product.workspace_id == workspace_id,
                Product.id == product_id,
                Product.deleted_at.is_(None),
            )
        )
        if product is None:
            raise TaxonomyProductNotFoundError("Product not found")
        return product


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return " ".join(parts) or None
    return None
