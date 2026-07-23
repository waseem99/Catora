from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from export_sales_demo_shopify_csv import export
from validate_sales_demo_shopify_csv import (
    EXPECTED_PRODUCTS,
    EXPECTED_VARIANTS,
    validate,
)

STORE_DOMAIN = "northstar-living-demo.myshopify.com"
MANIFEST_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def build(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "northstar-shopify-products.csv"
    manifest_path = output_dir / "northstar-shopify-manifest.json"

    product_count, variant_count = await export(csv_path)
    validate(csv_path)
    if product_count != EXPECTED_PRODUCTS or variant_count != EXPECTED_VARIANTS:
        raise RuntimeError("Northstar package counts do not match the acceptance contract")

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "store_domain": STORE_DOMAIN,
        "product_count": product_count,
        "variant_count": variant_count,
        "csv_file": csv_path.name,
        "csv_sha256": sha256(csv_path),
        "import_contract": {
            "overwrite_matching_handles": True,
            "publish_products": True,
            "expected_vendor": "Northstar Living",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return csv_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Northstar Shopify import package."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("northstar-shopify-demo-package"),
    )
    args = parser.parse_args()
    csv_path, manifest_path = asyncio.run(build(args.output_dir))
    print(f"Built {csv_path}")
    print(f"Built {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
