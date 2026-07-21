"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ProductDetailSchema,
  ProductProvenanceResponseSchema,
  type ProductDetail,
  type ProductProvenanceResponse,
} from "@catora/contracts";
import { apiRequest } from "@/lib/auth";
import {
  catalogProductPath,
  catalogProvenancePath,
  formatCatalogValue,
} from "@/lib/catalog";

type Props = { workspaceId: string; productId: string };

export function ProductDetailPanel({ workspaceId, productId }: Props) {
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [provenance, setProvenance] = useState<ProductProvenanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      apiRequest<unknown>(catalogProductPath(workspaceId, productId), {
        signal: controller.signal,
      }),
      apiRequest<unknown>(catalogProvenancePath(workspaceId, productId), {
        signal: controller.signal,
      }),
    ])
      .then(([productPayload, provenancePayload]) => {
        setProduct(ProductDetailSchema.parse(productPayload));
        setProvenance(ProductProvenanceResponseSchema.parse(provenancePayload));
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "Unable to load product");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [productId, workspaceId]);

  if (loading && !product) {
    return <p className="loading-state">Loading product evidence…</p>;
  }
  if (error) {
    return <p className="form-error" role="alert">{error}</p>;
  }
  if (!product) return null;

  return (
    <section className="catalog-panel">
      <header className="catalog-header">
        <div>
          <p className="eyebrow">CANONICAL PRODUCT</p>
          <h1>{product.title}</h1>
          <p className="canonical-key">{product.canonical_key}</p>
        </div>
        <div className="detail-actions">
          <span className={product.warning_count > 0 ? "warning-pill" : "clean-pill"}>
            {product.warning_count > 0 ? `${product.warning_count} warnings` : "Clean"}
          </span>
          <Link className="secondary" href={`/workspace/${workspaceId}/products`}>
            Back to products
          </Link>
        </div>
      </header>

      <section className="detail-grid" aria-label="Product summary">
        <article className="detail-card">
          <span>Status</span>
          <strong>{product.status}</strong>
        </article>
        <article className="detail-card">
          <span>Variants</span>
          <strong>{product.variants.length}</strong>
        </article>
        <article className="detail-card">
          <span>Evidence references</span>
          <strong>{product.provenance_count}</strong>
        </article>
      </section>

      <section className="catalog-section">
        <header><h2>Product attributes</h2></header>
        <AttributeTable attributes={product.product_attributes} />
      </section>

      <section className="catalog-section">
        <header><h2>Variants</h2></header>
        <div className="variant-grid">
          {product.variants.map((variant) => (
            <article className="variant-card" key={variant.id}>
              <header>
                <div>
                  <strong>{variant.title || variant.sku || "Untitled variant"}</strong>
                  <small>{variant.canonical_key}</small>
                </div>
                {variant.is_retired ? <span className="warning-pill">Retired</span> : null}
              </header>
              {variant.sku ? <p><span>SKU</span> {variant.sku}</p> : null}
              {Object.keys(variant.option_values).length > 0 ? (
                <pre className="value-block">{formatCatalogValue(variant.option_values)}</pre>
              ) : null}
              <AttributeTable attributes={variant.attributes} compact />
              {variant.images.length > 0 ? (
                <ul className="image-list">
                  {variant.images.map((image) => (
                    <li key={image.id}>{image.alt_text || image.url}</li>
                  ))}
                </ul>
              ) : null}
            </article>
          ))}
          {product.variants.length === 0 ? <p className="empty-state">No active variants.</p> : null}
        </div>
      </section>

      <section className="catalog-section">
        <header>
          <h2>Source provenance</h2>
          <span>{provenance?.total ?? 0} references</span>
        </header>
        <div className="evidence-list">
          {provenance?.items.map((evidence) => (
            <article className="evidence-row" key={evidence.id}>
              <div>
                <strong>{evidence.attribute_key || evidence.field_path}</strong>
                <small>{evidence.catalog_source_name} · {evidence.source_type}</small>
              </div>
              <p>{evidence.excerpt || "No excerpt retained"}</p>
              <dl>
                <div><dt>Source record</dt><dd>{evidence.external_id}</dd></div>
                <div><dt>Snapshot</dt><dd>{formatDate(evidence.snapshot_at)}</dd></div>
                <div><dt>Field path</dt><dd>{evidence.field_path}</dd></div>
              </dl>
            </article>
          ))}
        </div>
        {provenance?.items.length === 0 ? (
          <p className="empty-state">No evidence references are available.</p>
        ) : null}
      </section>
    </section>
  );
}

type Attribute = ProductDetail["product_attributes"][number];

function AttributeTable({
  attributes,
  compact = false,
}: {
  attributes: Attribute[];
  compact?: boolean;
}) {
  if (attributes.length === 0) {
    return <p className="empty-state">No attributes.</p>;
  }
  return (
    <div className={compact ? "attribute-table compact" : "attribute-table"}>
      {attributes.map((attribute) => (
        <div className="attribute-row" key={attribute.id}>
          <div>
            <strong>{attribute.key}</strong>
            <small>{attribute.value_type}{attribute.unit ? ` · ${attribute.unit}` : ""}</small>
          </div>
          <pre className="value-block">{formatCatalogValue(attribute.value)}</pre>
          <div className="attribute-state">
            <span>{attribute.value_state}</span>
            <span>{attribute.confidence}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
