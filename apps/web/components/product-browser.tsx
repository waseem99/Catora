"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  ProductListResponseSchema,
  type ProductListResponse,
} from "@catora/contracts";
import { apiRequest } from "@/lib/auth";
import { catalogProductsPath } from "@/lib/catalog";

type WarningFilter = "all" | "warnings" | "clean";
type Props = { workspaceId: string };

const pageSize = 25;

export function ProductBrowser({ workspaceId }: Props) {
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [warningFilter, setWarningFilter] = useState<WarningFilter>("all");
  const [offset, setOffset] = useState(0);
  const [response, setResponse] = useState<ProductListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const hasWarnings =
      warningFilter === "all" ? undefined : warningFilter === "warnings";
    setLoading(true);
    setError(null);
    apiRequest<unknown>(
      catalogProductsPath(workspaceId, {
        query,
        hasWarnings,
        limit: pageSize,
        offset,
      }),
      { signal: controller.signal },
    )
      .then((payload) => setResponse(ProductListResponseSchema.parse(payload)))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "Unable to load products");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset, query, warningFilter, workspaceId]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setQuery(draftQuery.trim());
  }

  function changeWarningFilter(value: WarningFilter) {
    setOffset(0);
    setWarningFilter(value);
  }

  const start = response && response.total > 0 ? response.offset + 1 : 0;
  const end = response ? Math.min(response.offset + response.items.length, response.total) : 0;
  const hasPrevious = offset > 0;
  const hasNext = response ? offset + response.items.length < response.total : false;

  return (
    <section className="catalog-panel" aria-busy={loading}>
      <header className="catalog-header">
        <div>
          <p className="eyebrow">CANONICAL CATALOG</p>
          <h1>Products</h1>
          <p className="lede">
            Search normalized products, inspect warnings and trace every value to source evidence.
          </p>
        </div>
        <Link className="secondary" href={`/workspace/${workspaceId}`}>
          Workspace home
        </Link>
      </header>

      <form className="catalog-toolbar" onSubmit={submitSearch}>
        <label>
          <span>Search title, canonical key or SKU</span>
          <input
            aria-label="Search products"
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="Cloud sofa or SOFA-BLUE"
            value={draftQuery}
          />
        </label>
        <label>
          <span>Normalization state</span>
          <select
            aria-label="Filter by normalization state"
            onChange={(event) => changeWarningFilter(event.target.value as WarningFilter)}
            value={warningFilter}
          >
            <option value="all">All products</option>
            <option value="warnings">Needs review</option>
            <option value="clean">No warnings</option>
          </select>
        </label>
        <button className="primary-button" type="submit">Search</button>
      </form>

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {loading && !response ? <p className="loading-state">Loading products…</p> : null}

      {response ? (
        <>
          <div className="catalog-summary" aria-live="polite">
            <span>{response.total} products</span>
            <span>{start}–{end}</span>
          </div>
          <div className="product-list">
            {response.items.map((product) => (
              <Link
                className="product-row"
                href={`/workspace/${workspaceId}/products/${product.id}`}
                key={product.id}
              >
                <div className="product-title-cell">
                  <strong>{product.title}</strong>
                  <small>{product.canonical_key}</small>
                </div>
                <dl className="product-metrics">
                  <div><dt>Variants</dt><dd>{product.variant_count}</dd></div>
                  <div><dt>Attributes</dt><dd>{product.attribute_count}</dd></div>
                  <div><dt>Images</dt><dd>{product.image_count}</dd></div>
                </dl>
                <span className={product.warning_count > 0 ? "warning-pill" : "clean-pill"}>
                  {product.warning_count > 0
                    ? `${product.warning_count} warning${product.warning_count === 1 ? "" : "s"}`
                    : "Clean"}
                </span>
              </Link>
            ))}
          </div>
          {response.items.length === 0 ? (
            <p className="empty-state">No products match the current filters.</p>
          ) : null}
          <div className="pagination-row">
            <button
              className="secondary-button"
              disabled={!hasPrevious || loading}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              type="button"
            >
              Previous
            </button>
            <button
              className="secondary-button"
              disabled={!hasNext || loading}
              onClick={() => setOffset(offset + pageSize)}
              type="button"
            >
              Next
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
