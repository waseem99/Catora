from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from catora_api.auth.dependencies import (
    AuthContextDependency,
    AuthServiceDependency,
    SessionDependency,
)
from catora_api.db.models.catalog import (
    CatalogSource,
    EvidenceReference,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    SourceRecord,
)
from catora_api.schemas.catalog import (
    EvidenceReferenceView,
    ProductAttributeView,
    ProductDetailView,
    ProductImageView,
    ProductListItem,
    ProductListResponse,
    ProductProvenanceResponse,
    ProductVariantView,
)

router = APIRouter(prefix="/api/v1", tags=["canonical catalog"])


@router.get(
    "/workspaces/{workspace_id}/products",
    response_model=ProductListResponse,
)
async def list_products(
    workspace_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    query: Annotated[str | None, Query(max_length=200)] = None,
    product_status: Annotated[
        str | None,
        Query(alias="status", min_length=1, max_length=30),
    ] = "active",
    has_warnings: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductListResponse:
    await auth_service.membership(session, context.user.id, workspace_id)

    product_filter = select(Product).where(
        Product.workspace_id == workspace_id,
        Product.deleted_at.is_(None),
    )
    count_filter = select(func.count()).select_from(Product).where(
        Product.workspace_id == workspace_id,
        Product.deleted_at.is_(None),
    )
    if product_status is not None:
        product_filter = product_filter.where(Product.status == product_status)
        count_filter = count_filter.where(Product.status == product_status)
    search_text = query.strip() if query else ""
    if search_text:
        pattern = f"%{_escape_like(search_text)}%"
        variant_match = exists(
            select(1).where(
                ProductVariant.workspace_id == workspace_id,
                ProductVariant.product_id == Product.id,
                ProductVariant.deleted_at.is_(None),
                or_(
                    ProductVariant.sku.ilike(pattern, escape="\\"),
                    ProductVariant.title.ilike(pattern, escape="\\"),
                ),
            )
        )
        search_filter = or_(
            Product.title.ilike(pattern, escape="\\"),
            Product.canonical_key.ilike(pattern, escape="\\"),
            variant_match,
        )
        product_filter = product_filter.where(search_filter)
        count_filter = count_filter.where(search_filter)
    if has_warnings is not None:
        warning_exists = _warning_exists(workspace_id)
        warning_filter = warning_exists if has_warnings else ~warning_exists
        product_filter = product_filter.where(warning_filter)
        count_filter = count_filter.where(warning_filter)

    total = int((await session.scalar(count_filter)) or 0)
    products = (
        await session.scalars(
            product_filter
            .order_by(Product.updated_at.desc(), Product.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    counts = await _product_counts(
        session,
        workspace_id=workspace_id,
        product_ids=[product.id for product in products],
    )
    return ProductListResponse(
        items=[
            ProductListItem(
                id=product.id,
                canonical_key=product.canonical_key,
                title=product.title,
                primary_category_id=product.primary_category_id,
                status=product.status,
                variant_count=counts.variants.get(product.id, 0),
                attribute_count=counts.attributes.get(product.id, 0),
                image_count=counts.images.get(product.id, 0),
                warning_count=counts.warnings.get(product.id, 0),
                created_at=product.created_at,
                updated_at=product.updated_at,
            )
            for product in products
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/workspaces/{workspace_id}/products/{product_id}",
    response_model=ProductDetailView,
)
async def get_product(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    include_retired_variants: bool = False,
) -> ProductDetailView:
    await auth_service.membership(session, context.user.id, workspace_id)
    product = await _product_or_404(session, workspace_id, product_id)

    variant_query = select(ProductVariant).where(
        ProductVariant.workspace_id == workspace_id,
        ProductVariant.product_id == product.id,
    )
    if not include_retired_variants:
        variant_query = variant_query.where(ProductVariant.deleted_at.is_(None))
    variants = (
        await session.scalars(
            variant_query.order_by(ProductVariant.canonical_key, ProductVariant.id)
        )
    ).all()
    variant_ids = [variant.id for variant in variants]

    attributes = (
        await session.scalars(
            select(ProductAttribute)
            .where(
                ProductAttribute.workspace_id == workspace_id,
                ProductAttribute.product_id == product.id,
                or_(
                    ProductAttribute.variant_id.is_(None),
                    ProductAttribute.variant_id.in_(variant_ids),
                ),
            )
            .order_by(
                ProductAttribute.variant_id.nullsfirst(),
                ProductAttribute.key,
                ProductAttribute.id,
            )
        )
    ).all()
    images = (
        await session.scalars(
            select(ProductImage)
            .where(
                ProductImage.workspace_id == workspace_id,
                ProductImage.product_id == product.id,
                or_(
                    ProductImage.variant_id.is_(None),
                    ProductImage.variant_id.in_(variant_ids),
                ),
            )
            .order_by(
                ProductImage.variant_id.nullsfirst(),
                ProductImage.position,
                ProductImage.id,
            )
        )
    ).all()
    provenance_count = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(EvidenceReference)
                .where(
                    EvidenceReference.workspace_id == workspace_id,
                    EvidenceReference.product_id == product.id,
                )
            )
        )
        or 0
    )
    return _product_detail(
        product,
        variants=variants,
        attributes=attributes,
        images=images,
        provenance_count=provenance_count,
    )


@router.get(
    "/workspaces/{workspace_id}/products/{product_id}/provenance",
    response_model=ProductProvenanceResponse,
)
async def get_product_provenance(
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDependency,
    auth_service: AuthServiceDependency,
    context: AuthContextDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductProvenanceResponse:
    await auth_service.membership(session, context.user.id, workspace_id)
    await _product_or_404(session, workspace_id, product_id)

    evidence_filter = (
        EvidenceReference.workspace_id == workspace_id,
        EvidenceReference.product_id == product_id,
        SourceRecord.workspace_id == workspace_id,
        CatalogSource.workspace_id == workspace_id,
    )
    total = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(EvidenceReference)
                .join(SourceRecord, SourceRecord.id == EvidenceReference.source_record_id)
                .join(
                    CatalogSource,
                    CatalogSource.id == SourceRecord.catalog_source_id,
                )
                .where(*evidence_filter)
            )
        )
        or 0
    )
    rows = (
        await session.execute(
            select(
                EvidenceReference,
                SourceRecord,
                CatalogSource,
                ProductAttribute.key,
            )
            .join(SourceRecord, SourceRecord.id == EvidenceReference.source_record_id)
            .join(
                CatalogSource,
                CatalogSource.id == SourceRecord.catalog_source_id,
            )
            .outerjoin(
                ProductAttribute,
                and_(
                    ProductAttribute.id == EvidenceReference.attribute_id,
                    ProductAttribute.workspace_id == workspace_id,
                ),
            )
            .where(*evidence_filter)
            .order_by(EvidenceReference.created_at, EvidenceReference.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items: list[EvidenceReferenceView] = []
    for row in rows:
        evidence = cast(EvidenceReference, row[0])
        source_record = cast(SourceRecord, row[1])
        catalog_source = cast(CatalogSource, row[2])
        attribute_key = cast(str | None, row[3])
        items.append(
            EvidenceReferenceView(
                id=evidence.id,
                source_record_id=source_record.id,
                catalog_source_id=catalog_source.id,
                catalog_source_name=catalog_source.name,
                source_type=catalog_source.source_type,
                external_id=source_record.external_id,
                source_updated_at=source_record.source_updated_at,
                snapshot_at=source_record.snapshot_at,
                product_id=evidence.product_id,
                variant_id=evidence.variant_id,
                attribute_id=evidence.attribute_id,
                attribute_key=attribute_key,
                field_path=evidence.field_path,
                excerpt=evidence.excerpt,
                checksum=evidence.checksum,
                created_at=evidence.created_at,
            )
        )
    return ProductProvenanceResponse(
        product_id=product_id,
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


class _ProductCounts:
    def __init__(self) -> None:
        self.variants: dict[uuid.UUID, int] = {}
        self.attributes: dict[uuid.UUID, int] = {}
        self.images: dict[uuid.UUID, int] = {}
        self.warnings: dict[uuid.UUID, int] = {}


async def _product_counts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    product_ids: Sequence[uuid.UUID],
) -> _ProductCounts:
    counts = _ProductCounts()
    if not product_ids:
        return counts

    variant_rows = (
        await session.execute(
            select(ProductVariant.product_id, func.count(ProductVariant.id))
            .where(
                ProductVariant.workspace_id == workspace_id,
                ProductVariant.product_id.in_(product_ids),
                ProductVariant.deleted_at.is_(None),
            )
            .group_by(ProductVariant.product_id)
        )
    ).all()
    counts.variants = {row[0]: int(row[1]) for row in variant_rows}

    warning_condition = or_(
        ProductAttribute.confidence != "high",
        ProductAttribute.value_state != "present",
    )
    attribute_rows = (
        await session.execute(
            select(
                ProductAttribute.product_id,
                func.count(ProductAttribute.id),
                func.count(ProductAttribute.id).filter(warning_condition),
            )
            .outerjoin(
                ProductVariant,
                and_(
                    ProductVariant.id == ProductAttribute.variant_id,
                    ProductVariant.workspace_id == workspace_id,
                ),
            )
            .where(
                ProductAttribute.workspace_id == workspace_id,
                ProductAttribute.product_id.in_(product_ids),
                or_(
                    ProductAttribute.variant_id.is_(None),
                    ProductVariant.deleted_at.is_(None),
                ),
            )
            .group_by(ProductAttribute.product_id)
        )
    ).all()
    counts.attributes = {row[0]: int(row[1]) for row in attribute_rows}
    counts.warnings = {row[0]: int(row[2]) for row in attribute_rows}

    image_rows = (
        await session.execute(
            select(ProductImage.product_id, func.count(ProductImage.id))
            .outerjoin(
                ProductVariant,
                and_(
                    ProductVariant.id == ProductImage.variant_id,
                    ProductVariant.workspace_id == workspace_id,
                ),
            )
            .where(
                ProductImage.workspace_id == workspace_id,
                ProductImage.product_id.in_(product_ids),
                or_(
                    ProductImage.variant_id.is_(None),
                    ProductVariant.deleted_at.is_(None),
                ),
            )
            .group_by(ProductImage.product_id)
        )
    ).all()
    counts.images = {row[0]: int(row[1]) for row in image_rows}
    return counts


async def _product_or_404(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Product:
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.workspace_id == workspace_id,
            Product.deleted_at.is_(None),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def _product_detail(
    product: Product,
    *,
    variants: Sequence[ProductVariant],
    attributes: Sequence[ProductAttribute],
    images: Sequence[ProductImage],
    provenance_count: int,
) -> ProductDetailView:
    product_attributes = [
        _attribute_view(attribute)
        for attribute in attributes
        if attribute.variant_id is None
    ]
    product_images = [
        _image_view(image) for image in images if image.variant_id is None
    ]
    attributes_by_variant: dict[uuid.UUID, list[ProductAttributeView]] = {}
    for attribute in attributes:
        if attribute.variant_id is not None:
            attributes_by_variant.setdefault(attribute.variant_id, []).append(
                _attribute_view(attribute)
            )
    images_by_variant: dict[uuid.UUID, list[ProductImageView]] = {}
    for image in images:
        if image.variant_id is not None:
            images_by_variant.setdefault(image.variant_id, []).append(
                _image_view(image)
            )
    warning_count = sum(1 for attribute in attributes if _is_warning(attribute))
    return ProductDetailView(
        id=product.id,
        workspace_id=cast(uuid.UUID, product.workspace_id),
        canonical_key=product.canonical_key,
        title=product.title,
        primary_category_id=product.primary_category_id,
        status=product.status,
        product_attributes=product_attributes,
        product_images=product_images,
        variants=[
            ProductVariantView(
                id=variant.id,
                canonical_key=variant.canonical_key,
                sku=variant.sku,
                title=variant.title,
                option_values=variant.option_values,
                is_retired=variant.deleted_at is not None,
                attributes=attributes_by_variant.get(variant.id, []),
                images=images_by_variant.get(variant.id, []),
                created_at=variant.created_at,
                updated_at=variant.updated_at,
            )
            for variant in variants
        ],
        warning_count=warning_count,
        provenance_count=provenance_count,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _attribute_view(attribute: ProductAttribute) -> ProductAttributeView:
    return ProductAttributeView(
        id=attribute.id,
        variant_id=attribute.variant_id,
        key=attribute.key,
        value=attribute.value,
        value_type=attribute.value_type,
        unit=attribute.unit,
        locale=attribute.locale,
        value_state=attribute.value_state,  # type: ignore[arg-type]
        transformer_version=attribute.transformer_version,
        confidence=attribute.confidence,  # type: ignore[arg-type]
        created_at=attribute.created_at,
        updated_at=attribute.updated_at,
    )


def _image_view(image: ProductImage) -> ProductImageView:
    return ProductImageView.model_validate(image)


def _warning_exists(workspace_id: uuid.UUID) -> Exists:
    return exists(
        select(1)
        .select_from(ProductAttribute)
        .outerjoin(
            ProductVariant,
            and_(
                ProductVariant.id == ProductAttribute.variant_id,
                ProductVariant.workspace_id == workspace_id,
            ),
        )
        .where(
            ProductAttribute.workspace_id == workspace_id,
            ProductAttribute.product_id == Product.id,
            or_(
                ProductAttribute.variant_id.is_(None),
                ProductVariant.deleted_at.is_(None),
            ),
            or_(
                ProductAttribute.confidence != "high",
                ProductAttribute.value_state != "present",
            ),
        )
    )


def _is_warning(attribute: ProductAttribute) -> bool:
    return attribute.confidence != "high" or attribute.value_state != "present"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
