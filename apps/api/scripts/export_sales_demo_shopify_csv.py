from __future__ import annotations

import argparse
import asyncio
import csv
import uuid
from pathlib import Path
from typing import cast

from seed_sales_demo import WORKSPACE_SLUG
from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models.catalog import (
    Category,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
)
from catora_api.db.models.identity import Workspace

HEADERS = (
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Image Src",
    "Image Alt Text",
    "Status",
    "Width (product.metafields.custom.width_mm)",
    "Material (product.metafields.custom.material)",
    "Care instructions (product.metafields.custom.care_instructions)",
    "Assembly required (product.metafields.custom.assembly_required)",
    "Warranty months (product.metafields.custom.warranty_months)",
)


def _handle(product: Product) -> str:
    return product.canonical_key.replace(":", "-").replace("_", "-")


def _string_value(attribute: ProductAttribute | None) -> str:
    if attribute is None or attribute.value_state != "present" or attribute.value is None:
        return ""
    if isinstance(attribute.value, bool):
        return "true" if attribute.value else "false"
    return str(attribute.value)


async def export(path: Path) -> tuple[int, int]:
    async with SessionFactory() as session:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == WORKSPACE_SLUG)
        )
        if workspace is None:
            raise RuntimeError("The sales-demo workspace does not exist; run demo:seed first")

        products = cast(
            list[Product],
            (
                await session.scalars(
                    select(Product)
                    .where(
                        Product.workspace_id == workspace.id,
                        Product.deleted_at.is_(None),
                    )
                    .order_by(Product.canonical_key)
                )
            ).all(),
        )
        variants = cast(
            list[ProductVariant],
            (
                await session.scalars(
                    select(ProductVariant)
                    .where(
                        ProductVariant.workspace_id == workspace.id,
                        ProductVariant.deleted_at.is_(None),
                    )
                    .order_by(ProductVariant.product_id, ProductVariant.sku, ProductVariant.id)
                )
            ).all(),
        )
        attributes = cast(
            list[ProductAttribute],
            (
                await session.scalars(
                    select(ProductAttribute)
                    .where(
                        ProductAttribute.workspace_id == workspace.id,
                        ProductAttribute.variant_id.is_(None),
                    )
                    .order_by(ProductAttribute.product_id, ProductAttribute.key)
                )
            ).all(),
        )
        categories = cast(
            list[Category],
            (
                await session.scalars(
                    select(Category).where(Category.workspace_id == workspace.id)
                )
            ).all(),
        )
        images = cast(
            list[ProductImage],
            (
                await session.scalars(
                    select(ProductImage)
                    .where(ProductImage.workspace_id == workspace.id)
                    .order_by(ProductImage.product_id, ProductImage.position, ProductImage.id)
                )
            ).all(),
        )

    variants_by_product: dict[uuid.UUID, list[ProductVariant]] = {}
    for variant in variants:
        variants_by_product.setdefault(variant.product_id, []).append(variant)
    attributes_by_product: dict[uuid.UUID, dict[str, ProductAttribute]] = {}
    for attribute in attributes:
        attributes_by_product.setdefault(attribute.product_id, {})[attribute.key] = attribute
    categories_by_id = {category.id: category for category in categories}
    images_by_product: dict[uuid.UUID, ProductImage] = {}
    for image in images:
        images_by_product.setdefault(image.product_id, image)

    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for product in products:
            product_variants = variants_by_product.get(product.id, [])
            if not product_variants:
                continue
            category = categories_by_id.get(product.primary_category_id)
            product_attributes = attributes_by_product.get(product.id, {})
            image = images_by_product.get(product.id)
            product_handle = _handle(product)
            category_label = category.label if category is not None else "Furniture"
            for variant_index, variant in enumerate(product_variants):
                option_value = str(variant.option_values.get("colour", "Default Title"))
                row = {
                    "Handle": product_handle,
                    "Title": product.title if variant_index == 0 else "",
                    "Body (HTML)": (
                        f"<p>Northstar Living {category_label.lower()} for modern homes.</p>"
                        if variant_index == 0
                        else ""
                    ),
                    "Vendor": "Northstar Living" if variant_index == 0 else "",
                    "Type": category_label if variant_index == 0 else "",
                    "Tags": "sales-demo, furniture, catora" if variant_index == 0 else "",
                    "Published": "TRUE" if variant_index == 0 else "",
                    "Option1 Name": "Colour",
                    "Option1 Value": option_value,
                    "Variant SKU": variant.sku or "",
                    "Variant Grams": "25000",
                    "Variant Inventory Tracker": "shopify",
                    "Variant Inventory Qty": "25",
                    "Variant Inventory Policy": "deny",
                    "Variant Fulfillment Service": "manual",
                    "Variant Price": f"{349 + (row_count % 17) * 25}.00",
                    "Variant Requires Shipping": "TRUE",
                    "Variant Taxable": "TRUE",
                    "Image Src": image.url if variant_index == 0 and image is not None else "",
                    "Image Alt Text": (
                        image.alt_text or ""
                        if variant_index == 0 and image is not None
                        else ""
                    ),
                    "Status": "active" if variant_index == 0 else "",
                    "Width (product.metafields.custom.width_mm)": (
                        _string_value(product_attributes.get("width_mm"))
                        if variant_index == 0
                        else ""
                    ),
                    "Material (product.metafields.custom.material)": (
                        _string_value(product_attributes.get("material"))
                        if variant_index == 0
                        else ""
                    ),
                    "Care instructions (product.metafields.custom.care_instructions)": (
                        _string_value(product_attributes.get("care_instructions"))
                        if variant_index == 0
                        else ""
                    ),
                    "Assembly required (product.metafields.custom.assembly_required)": (
                        _string_value(product_attributes.get("assembly_required"))
                        if variant_index == 0
                        else ""
                    ),
                    "Warranty months (product.metafields.custom.warranty_months)": (
                        _string_value(product_attributes.get("warranty_months"))
                        if variant_index == 0
                        else ""
                    ),
                }
                writer.writerow(row)
                row_count += 1

    return len(products), row_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the deterministic Northstar showcase as a Shopify product CSV."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("northstar-shopify-products.csv"),
    )
    args = parser.parse_args()
    product_count, variant_count = asyncio.run(export(args.output))
    print(
        f"Wrote {args.output}: {product_count} products and {variant_count} variant rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
