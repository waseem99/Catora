import {
  CatalogBridgeProductSchema,
  type CatalogBridgeImage,
  type CatalogBridgeJsonValue,
  type CatalogBridgeProduct,
  type CatalogBridgeSnapshotStatus,
  type CatalogBridgeVariant,
} from "@catora/contracts";
import {
  CatalogBridgeClient,
  type CatalogBridgeClientOptions,
} from "./client.js";

export type FieldSelector<T> =
  | string
  | readonly string[]
  | ((document: T) => unknown);

export interface MongoCatalogFieldMap<T> {
  id?: FieldSelector<T>;
  title?: FieldSelector<T>;
  description?: FieldSelector<T>;
  slug?: FieldSelector<T>;
  url?: FieldSelector<T>;
  canonicalUrl?: FieldSelector<T>;
  status?: FieldSelector<T>;
  brand?: FieldSelector<T>;
  productType?: FieldSelector<T>;
  categories?: FieldSelector<T>;
  collections?: FieldSelector<T>;
  tags?: FieldSelector<T>;
  attributes?: FieldSelector<T>;
  seoTitle?: FieldSelector<T>;
  seoDescription?: FieldSelector<T>;
  images?: FieldSelector<T>;
  variants?: FieldSelector<T>;
  createdAt?: FieldSelector<T>;
  updatedAt?: FieldSelector<T>;
}

interface MongoQueryLike<T> {
  sort(value: Record<string, 1 | -1>): MongoQueryLike<T>;
  limit(value: number): MongoQueryLike<T>;
  lean(): MongoQueryLike<T>;
  exec(): Promise<T[]>;
}

export interface MongoModelLike<T> {
  find(filter?: Record<string, unknown>): MongoQueryLike<T>;
}

export interface MongoCatalogSourceOptions<T> {
  model: MongoModelLike<T>;
  filter?: Record<string, unknown>;
  fields?: MongoCatalogFieldMap<T>;
  pageSize?: number;
  cursorField?: string;
  mapProduct?: (
    document: T,
    inferred: CatalogBridgeProduct,
  ) => CatalogBridgeProduct | Promise<CatalogBridgeProduct>;
}

export interface MongoCatalogInspection {
  productCount: number;
  variantCount: number;
  invalidCount: number;
  errors: Array<{ product: string; message: string }>;
}

export interface RunMongoCatalogBridgeOptions<T>
  extends MongoCatalogSourceOptions<T>,
    Omit<CatalogBridgeClientOptions, "onProgress"> {
  dryRun?: boolean;
  sourceLabel?: string;
  metadata?: Record<string, string>;
  maxValidationErrors?: number;
  onProgress?: CatalogBridgeClientOptions["onProgress"];
}

export interface RunMongoCatalogBridgeResult {
  inspection: MongoCatalogInspection;
  status: CatalogBridgeSnapshotStatus | null;
}

const ForbiddenKeyPattern =
  /(^|[_\-.])(customer|customers|order|orders|payment|payments|password|passwords|session|sessions|token|tokens|address|addresses)([_\-.]|$)/i;

const DefaultFields = {
  id: ["_id", "id", "productId", "product_id"],
  title: ["title", "name", "productName", "product_name"],
  description: ["description", "descriptionHtml", "body", "details"],
  slug: ["slug", "handle"],
  url: ["url", "productUrl", "product_url", "link"],
  canonicalUrl: ["canonicalUrl", "canonical_url"],
  status: ["status", "state", "availabilityStatus"],
  brand: ["brand", "vendor", "manufacturer"],
  productType: ["productType", "product_type", "type"],
  categories: ["categories", "category", "categoryNames"],
  collections: ["collections", "collectionNames"],
  tags: ["tags", "labels"],
  attributes: ["attributes", "specifications", "specs", "features"],
  seoTitle: ["seo.title", "seoTitle", "seo_title", "meta.title"],
  seoDescription: [
    "seo.description",
    "seoDescription",
    "seo_description",
    "meta.description",
  ],
  images: ["images", "media", "gallery"],
  variants: ["variants", "productVariants", "product_variants", "skus"],
  createdAt: ["createdAt", "created_at"],
  updatedAt: ["updatedAt", "updated_at", "modifiedAt"],
} as const;

function readPath(value: unknown, path: string): unknown {
  let current = value;
  for (const segment of path.split(".")) {
    if (current === null || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function select<T>(
  document: T,
  selector: FieldSelector<T> | undefined,
  fallbacks: readonly string[],
): unknown {
  if (typeof selector === "function") {
    return selector(document);
  }
  const paths =
    typeof selector === "string"
      ? [selector]
      : selector === undefined
        ? fallbacks
        : selector;
  for (const path of paths) {
    const value = readPath(document, path);
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }
  return undefined;
}

function text(value: unknown): string | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  const candidate = String(value).trim();
  return candidate || undefined;
}

function timestamp(value: unknown): string | undefined {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString();
  }
  if (typeof value === "string" || typeof value === "number") {
    const candidate = new Date(value);
    if (!Number.isNaN(candidate.getTime())) {
      return candidate.toISOString();
    }
  }
  return undefined;
}

function stringList(value: unknown): string[] | undefined {
  const source = Array.isArray(value) ? value : value === undefined ? [] : [value];
  const result = source
    .map((item) => {
      if (item && typeof item === "object") {
        return text(
          (item as Record<string, unknown>).name ??
            (item as Record<string, unknown>).title ??
            (item as Record<string, unknown>).label,
        );
      }
      return text(item);
    })
    .filter((item): item is string => Boolean(item));
  return result.length > 0 ? [...new Set(result)] : undefined;
}

function safeJsonValue(value: unknown, depth = 0): CatalogBridgeJsonValue | undefined {
  if (depth > 8 || value === undefined) {
    return undefined;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => safeJsonValue(item, depth + 1))
      .filter((item): item is CatalogBridgeJsonValue => item !== undefined);
  }
  if (typeof value === "object") {
    const output: Record<string, CatalogBridgeJsonValue> = {};
    for (const [key, item] of Object.entries(value)) {
      if (ForbiddenKeyPattern.test(key) || key.startsWith("__")) {
        continue;
      }
      const normalized = safeJsonValue(item, depth + 1);
      if (normalized !== undefined) {
        output[key] = normalized;
      }
    }
    return output;
  }
  return text(value);
}

function attributeMap(value: unknown): Record<string, CatalogBridgeJsonValue> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const safe = safeJsonValue(value);
  if (!safe || typeof safe !== "object" || Array.isArray(safe)) {
    return undefined;
  }
  return Object.keys(safe).length > 0 ? safe : undefined;
}

function mapImage(value: unknown, position: number): CatalogBridgeImage | null {
  if (typeof value === "string") {
    return { url: value, position };
  }
  if (!value || typeof value !== "object") {
    return null;
  }
  const image = value as Record<string, unknown>;
  const url = text(image.url ?? image.src ?? image.secureUrl ?? image.location);
  if (!url) {
    return null;
  }
  return {
    url,
    altText: text(image.altText ?? image.alt ?? image.caption) ?? null,
    position:
      typeof image.position === "number" && Number.isInteger(image.position)
        ? image.position
        : position,
    variantId: text(image.variantId ?? image.variant_id) ?? null,
  };
}

function mapImages(value: unknown): CatalogBridgeImage[] | undefined {
  const source = Array.isArray(value) ? value : value === undefined ? [] : [value];
  const images = source
    .map((item, index) => mapImage(item, index))
    .filter((item): item is CatalogBridgeImage => item !== null);
  return images.length > 0 ? images : undefined;
}

function mapVariant(value: unknown, index: number): CatalogBridgeVariant | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const variant = value as Record<string, unknown>;
  const id = text(variant._id ?? variant.id ?? variant.variantId ?? variant.sku);
  if (!id) {
    return null;
  }
  const options = attributeMap(
    variant.options ?? variant.optionValues ?? variant.option_values,
  );
  const attributes = attributeMap(
    variant.attributes ?? variant.specifications ?? variant.specs,
  );
  return {
    id,
    sku: text(variant.sku ?? variant.code) ?? null,
    title: text(variant.title ?? variant.name) ?? null,
    price: text(variant.price ?? variant.salePrice ?? variant.sale_price) ?? null,
    compareAtPrice:
      text(variant.compareAtPrice ?? variant.compare_at_price ?? variant.regularPrice) ??
      null,
    currency: text(variant.currency)?.toUpperCase() ?? null,
    availability:
      text(variant.availability ?? variant.stockStatus ?? variant.stock_status) ?? null,
    options,
    attributes,
    images: mapImages(variant.images ?? variant.image),
    createdAt: timestamp(variant.createdAt ?? variant.created_at) ?? null,
    updatedAt: timestamp(variant.updatedAt ?? variant.updated_at) ?? null,
  };
}

function mapVariants(value: unknown): CatalogBridgeVariant[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const variants = value
    .map((item, index) => mapVariant(item, index))
    .filter((item): item is CatalogBridgeVariant => item !== null);
  return variants.length > 0 ? variants : undefined;
}

export function autoMapMongoProduct<T>(
  document: T,
  fields: MongoCatalogFieldMap<T> = {},
): CatalogBridgeProduct {
  const id = text(select(document, fields.id, DefaultFields.id));
  const title = text(select(document, fields.title, DefaultFields.title));
  const inferred = {
    id: id ?? "",
    title: title ?? "",
    description:
      text(select(document, fields.description, DefaultFields.description)) ?? null,
    slug: text(select(document, fields.slug, DefaultFields.slug)) ?? null,
    url: text(select(document, fields.url, DefaultFields.url)) ?? null,
    canonicalUrl:
      text(select(document, fields.canonicalUrl, DefaultFields.canonicalUrl)) ?? null,
    status: text(select(document, fields.status, DefaultFields.status)) ?? null,
    brand: text(select(document, fields.brand, DefaultFields.brand)) ?? null,
    productType:
      text(select(document, fields.productType, DefaultFields.productType)) ?? null,
    categories: stringList(
      select(document, fields.categories, DefaultFields.categories),
    ),
    collections: stringList(
      select(document, fields.collections, DefaultFields.collections),
    ),
    tags: stringList(select(document, fields.tags, DefaultFields.tags)),
    attributes: attributeMap(
      select(document, fields.attributes, DefaultFields.attributes),
    ),
    seo: {
      title:
        text(select(document, fields.seoTitle, DefaultFields.seoTitle)) ?? null,
      description:
        text(
          select(document, fields.seoDescription, DefaultFields.seoDescription),
        ) ?? null,
    },
    images: mapImages(select(document, fields.images, DefaultFields.images)),
    variants: mapVariants(select(document, fields.variants, DefaultFields.variants)),
    createdAt:
      timestamp(select(document, fields.createdAt, DefaultFields.createdAt)) ?? null,
    updatedAt:
      timestamp(select(document, fields.updatedAt, DefaultFields.updatedAt)) ?? null,
  } satisfies CatalogBridgeProduct;
  return CatalogBridgeProductSchema.parse(inferred);
}

function pagedFilter(
  base: Record<string, unknown>,
  cursorField: string,
  cursor: unknown,
): Record<string, unknown> {
  if (cursor === undefined) {
    return base;
  }
  return {
    $and: [base, { [cursorField]: { $gt: cursor } }],
  };
}

export async function* mongoCatalogProducts<T>(
  options: MongoCatalogSourceOptions<T>,
): AsyncIterable<CatalogBridgeProduct> {
  const cursorField = options.cursorField ?? "_id";
  const pageSize = options.pageSize ?? 250;
  if (pageSize < 1 || pageSize > 1_000) {
    throw new Error("Mongo bridge pageSize must be between 1 and 1000");
  }
  let cursor: unknown = undefined;
  for (;;) {
    const documents = await options.model
      .find(pagedFilter(options.filter ?? {}, cursorField, cursor))
      .sort({ [cursorField]: 1 })
      .limit(pageSize)
      .lean()
      .exec();
    if (documents.length === 0) {
      return;
    }
    for (const document of documents) {
      const inferred = autoMapMongoProduct(document, options.fields);
      const mapped = options.mapProduct
        ? await options.mapProduct(document, inferred)
        : inferred;
      yield CatalogBridgeProductSchema.parse(mapped);
    }
    const last = documents.at(-1);
    const nextCursor = readPath(last, cursorField);
    if (nextCursor === undefined || Object.is(nextCursor, cursor)) {
      throw new Error(
        `Mongo bridge cursor field '${cursorField}' must be stable and present on every document`,
      );
    }
    cursor = nextCursor;
    if (documents.length < pageSize) {
      return;
    }
  }
}

export async function inspectMongoCatalog<T>(
  options: MongoCatalogSourceOptions<T>,
  maxErrors = 25,
): Promise<MongoCatalogInspection> {
  let productCount = 0;
  let variantCount = 0;
  let invalidCount = 0;
  const errors: Array<{ product: string; message: string }> = [];
  try {
    for await (const product of mongoCatalogProducts(options)) {
      productCount += 1;
      variantCount += product.variants?.length ?? 0;
    }
  } catch (error) {
    invalidCount += 1;
    if (errors.length < maxErrors) {
      errors.push({
        product: `after:${productCount}`,
        message: error instanceof Error ? error.message : "Invalid catalog product",
      });
    }
  }
  return { productCount, variantCount, invalidCount, errors };
}

export async function runMongoCatalogBridge<T>(
  options: RunMongoCatalogBridgeOptions<T>,
): Promise<RunMongoCatalogBridgeResult> {
  const inspection = await inspectMongoCatalog(
    options,
    options.maxValidationErrors ?? 25,
  );
  if (inspection.invalidCount > 0) {
    throw new Error(
      `Catalog bridge validation failed: ${inspection.errors
        .map((item) => item.message)
        .join("; ")}`,
    );
  }
  if (options.dryRun) {
    return { inspection, status: null };
  }
  const client = new CatalogBridgeClient({
    endpoint: options.endpoint,
    sourceId: options.sourceId,
    token: options.token,
    batchSize: options.batchSize,
    maxAttempts: options.maxAttempts,
    retryBaseDelayMs: options.retryBaseDelayMs,
    fetchImplementation: options.fetchImplementation,
    checkpointStore: options.checkpointStore,
    onProgress: options.onProgress,
  });
  const status = await client.uploadSnapshot({
    products: mongoCatalogProducts(options),
    productCount: inspection.productCount,
    variantCount: inspection.variantCount,
    sourceLabel: options.sourceLabel,
    metadata: options.metadata,
  });
  return { inspection, status };
}
