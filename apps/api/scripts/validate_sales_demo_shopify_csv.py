from __future__ import annotations

import argparse
import csv
from pathlib import Path

EXPECTED_PRODUCTS = 1_000
EXPECTED_VARIANTS = 2_000


def validate(path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_VARIANTS:
        raise ValueError(
            f"Expected {EXPECTED_VARIANTS:,} variant rows, found {len(rows):,}"
        )
    titled_rows = sum(bool(row.get("Title")) for row in rows)
    if titled_rows != EXPECTED_PRODUCTS:
        raise ValueError(
            f"Expected {EXPECTED_PRODUCTS:,} product title rows, found {titled_rows:,}"
        )
    skus = [row.get("Variant SKU", "") for row in rows]
    if any(not sku for sku in skus):
        raise ValueError("Every Shopify variant row must have a SKU")
    unique_skus = len(set(skus))
    if unique_skus != EXPECTED_VARIANTS:
        raise ValueError(
            f"Expected {EXPECTED_VARIANTS:,} unique SKUs, found {unique_skus:,}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the deterministic Northstar Shopify CSV export."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    validate(args.path)
    print(
        f"Validated {EXPECTED_PRODUCTS:,} products and "
        f"{EXPECTED_VARIANTS:,} unique variant SKUs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
