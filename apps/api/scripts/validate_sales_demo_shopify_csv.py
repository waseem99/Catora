from __future__ import annotations

import argparse
import csv
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_PRODUCTS = 1_000
EXPECTED_VARIANTS = 2_000
EXPECTED_IMAGE_HOST = "catora.codistan.org"
EXPECTED_IMAGE_PREFIX = "/demo-product-images/"


def _validate_image_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Shopify image URL must use HTTPS: {url}")
    if parsed.hostname != EXPECTED_IMAGE_HOST:
        raise ValueError(
            f"Shopify image URL must use {EXPECTED_IMAGE_HOST}, found {parsed.hostname}"
        )
    if not parsed.path.startswith(EXPECTED_IMAGE_PREFIX) or not parsed.path.endswith(".png"):
        raise ValueError(f"Shopify image URL has an unexpected path: {url}")


def validate(path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_VARIANTS:
        raise ValueError(
            f"Expected {EXPECTED_VARIANTS:,} variant rows, found {len(rows):,}"
        )
    product_rows = [row for row in rows if row.get("Title")]
    if len(product_rows) != EXPECTED_PRODUCTS:
        raise ValueError(
            f"Expected {EXPECTED_PRODUCTS:,} product title rows, found {len(product_rows):,}"
        )
    skus = [row.get("Variant SKU", "") for row in rows]
    if any(not sku for sku in skus):
        raise ValueError("Every Shopify variant row must have a SKU")
    unique_skus = len(set(skus))
    if unique_skus != EXPECTED_VARIANTS:
        raise ValueError(
            f"Expected {EXPECTED_VARIANTS:,} unique SKUs, found {unique_skus:,}"
        )

    image_urls = [row.get("Image Src", "").strip() for row in product_rows]
    if any(not image_url for image_url in image_urls):
        raise ValueError("Every Northstar product must have a public image URL")
    for image_url in image_urls:
        _validate_image_url(image_url)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the deterministic Northstar Shopify CSV export."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    validate(args.path)
    print(
        f"Validated {EXPECTED_PRODUCTS:,} products, "
        f"{EXPECTED_VARIANTS:,} unique variant SKUs and public image URLs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
