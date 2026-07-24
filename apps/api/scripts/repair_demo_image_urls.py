from __future__ import annotations

import asyncio

from seed_sales_demo import WORKSPACE_SLUG, digest
from sqlalchemy import select

from catora_api.database import SessionFactory
from catora_api.db.models.catalog import Category, Product, ProductImage
from catora_api.db.models.identity import Workspace

DEMO_IMAGE_ORIGIN = "https://catora.codistan.org/demo-product-images"


async def repair() -> tuple[int, int]:
    async with SessionFactory() as session:
        rows = (
            await session.execute(
                select(ProductImage, Category.key)
                .join(Product, Product.id == ProductImage.product_id)
                .join(Category, Category.id == Product.primary_category_id)
                .join(Workspace, Workspace.id == ProductImage.workspace_id)
                .where(Workspace.slug == WORKSPACE_SLUG)
                .order_by(ProductImage.product_id, ProductImage.position, ProductImage.id)
            )
        ).all()

        updated = 0
        for image, category_key in rows:
            expected_url = f"{DEMO_IMAGE_ORIGIN}/{category_key}.png"
            if image.url == expected_url:
                continue
            image.url = expected_url
            image.checksum = digest(expected_url)
            updated += 1

        await session.commit()
        return len(rows), updated


def main() -> int:
    total, updated = asyncio.run(repair())
    print(
        "Catora demo image URLs ready: "
        f"{total:,} images checked, {updated:,} updated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
