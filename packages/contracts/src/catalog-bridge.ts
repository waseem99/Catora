import { z } from "zod";

export const CATALOG_BRIDGE_PROTOCOL_VERSION = "2026-07-bridge-v1" as const;
export const CATALOG_BRIDGE_MAX_BATCH_RECORDS = 250;

const ForbiddenFieldTokens = new Set([
  "customer",
  "customers",
  "order",
  "orders",
  "payment",
  "payments",
  "password",
  "passwords",
  "session",
  "sessions",
  "token",
  "tokens",
  "address",
  "addresses",
]);

function containsForbiddenFieldToken(value: string): boolean {
  const normalized = value.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
  return normalized
    .split(/[_\-.]+/)
    .some((token) => ForbiddenFieldTokens.has(token));
}

const SafeFieldKeySchema = z
  .string()
  .min(1)
  .max(160)
  .refine((value) => !containsForbiddenFieldToken(value), {
    message: "Sensitive or non-catalog field names are not allowed",
  });

export type CatalogBridgeJsonValue =
  | string
  | number
  | boolean
  | null
  | CatalogBridgeJsonValue[]
  | { [key: string]: CatalogBridgeJsonValue };

export const CatalogBridgeJsonValueSchema: z.ZodType<CatalogBridgeJsonValue> =
  z.lazy(() =>
    z.union([
      z.string().max(20_000),
      z.number().finite(),
      z.boolean(),
      z.null(),
      z.array(CatalogBridgeJsonValueSchema).max(500),
      z.record(SafeFieldKeySchema, CatalogBridgeJsonValueSchema),
    ]),
  );

export const CatalogBridgeSeoSchema = z
  .object({
    title: z.string().max(500).nullable().optional(),
    description: z.string().max(2_000).nullable().optional(),
  })
  .strict();

export const CatalogBridgeImageSchema = z
  .object({
    url: z.string().url().max(2_000),
    altText: z.string().max(1_000).nullable().optional(),
    position: z.number().int().nonnegative().max(10_000).optional(),
    variantId: z.string().min(1).max(500).nullable().optional(),
  })
  .strict();

export const CatalogBridgeVariantSchema = z
  .object({
    id: z.string().min(1).max(500),
    sku: z.string().max(500).nullable().optional(),
    title: z.string().max(1_000).nullable().optional(),
    price: z.string().max(100).nullable().optional(),
    compareAtPrice: z.string().max(100).nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    availability: z.string().max(100).nullable().optional(),
    options: z
      .record(SafeFieldKeySchema, CatalogBridgeJsonValueSchema)
      .optional(),
    attributes: z
      .record(SafeFieldKeySchema, CatalogBridgeJsonValueSchema)
      .optional(),
    images: z.array(CatalogBridgeImageSchema).max(100).optional(),
    createdAt: z.string().datetime().nullable().optional(),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict();

export const CatalogBridgeProductSchema = z
  .object({
    id: z.string().min(1).max(500),
    title: z.string().min(1).max(1_000),
    description: z.string().max(100_000).nullable().optional(),
    slug: z.string().max(1_000).nullable().optional(),
    url: z.string().url().max(2_000).nullable().optional(),
    canonicalUrl: z.string().url().max(2_000).nullable().optional(),
    status: z.string().max(100).nullable().optional(),
    brand: z.string().max(500).nullable().optional(),
    productType: z.string().max(500).nullable().optional(),
    categories: z.array(z.string().min(1).max(500)).max(100).optional(),
    collections: z.array(z.string().min(1).max(500)).max(100).optional(),
    tags: z.array(z.string().min(1).max(500)).max(500).optional(),
    attributes: z
      .record(SafeFieldKeySchema, CatalogBridgeJsonValueSchema)
      .optional(),
    seo: CatalogBridgeSeoSchema.optional(),
    images: z.array(CatalogBridgeImageSchema).max(500).optional(),
    variants: z.array(CatalogBridgeVariantSchema).max(2_000).optional(),
    createdAt: z.string().datetime().nullable().optional(),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict()
  .superRefine((product, context) => {
    const variantIds = new Set<string>();
    for (const [index, variant] of (product.variants ?? []).entries()) {
      if (variantIds.has(variant.id)) {
        context.addIssue({
          code: "custom",
          path: ["variants", index, "id"],
          message: "Variant IDs must be unique inside a product",
        });
      }
      variantIds.add(variant.id);
    }
    for (const [index, image] of (product.images ?? []).entries()) {
      if (image.variantId && !variantIds.has(image.variantId)) {
        context.addIssue({
          code: "custom",
          path: ["images", index, "variantId"],
          message:
            "Image variantId must reference a variant in the same product",
        });
      }
    }
  });

export const CatalogBridgeSnapshotManifestSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    snapshotId: z.string().uuid(),
    startedAt: z.string().datetime(),
    declaredProductCount: z.number().int().nonnegative(),
    declaredVariantCount: z.number().int().nonnegative(),
    sourceLabel: z.string().min(1).max(200).optional(),
    metadata: z.record(SafeFieldKeySchema, z.string().max(500)).optional(),
  })
  .strict();

export const CatalogBridgeBatchSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    snapshotId: z.string().uuid(),
    sequence: z.number().int().nonnegative(),
    records: z
      .array(CatalogBridgeProductSchema)
      .min(1)
      .max(CATALOG_BRIDGE_MAX_BATCH_RECORDS),
  })
  .strict();

export const CatalogBridgeCompleteRequestSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    snapshotId: z.string().uuid(),
    batchCount: z.number().int().positive(),
    productCount: z.number().int().nonnegative(),
    variantCount: z.number().int().nonnegative(),
  })
  .strict();

export const CatalogBridgeSourceProvisionResponseSchema = z
  .object({
    sourceId: z.string().uuid(),
    endpoint: z.string().url(),
    token: z.string().min(32),
    tokenFingerprint: z.string().length(12),
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
  })
  .strict();

export const CatalogBridgeSnapshotStatusSchema = z
  .object({
    sourceId: z.string().uuid(),
    snapshotId: z.string().uuid(),
    status: z.enum([
      "receiving",
      "queued",
      "processing",
      "completed",
      "failed",
    ]),
    acceptedBatches: z.number().int().nonnegative(),
    acceptedProducts: z.number().int().nonnegative(),
    acceptedVariants: z.number().int().nonnegative(),
    ingestionJobId: z.string().uuid().nullable(),
  })
  .strict();

export type CatalogBridgeProduct = z.infer<typeof CatalogBridgeProductSchema>;
export type CatalogBridgeVariant = z.infer<typeof CatalogBridgeVariantSchema>;
export type CatalogBridgeImage = z.infer<typeof CatalogBridgeImageSchema>;
export type CatalogBridgeSnapshotManifest = z.infer<
  typeof CatalogBridgeSnapshotManifestSchema
>;
export type CatalogBridgeBatch = z.infer<typeof CatalogBridgeBatchSchema>;
export type CatalogBridgeCompleteRequest = z.infer<
  typeof CatalogBridgeCompleteRequestSchema
>;
export type CatalogBridgeSourceProvisionResponse = z.infer<
  typeof CatalogBridgeSourceProvisionResponseSchema
>;
export type CatalogBridgeSnapshotStatus = z.infer<
  typeof CatalogBridgeSnapshotStatusSchema
>;
