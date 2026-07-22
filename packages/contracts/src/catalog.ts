import { z } from "zod";

export const CatalogJsonValueSchema = z.union([
  z.record(z.string(), z.unknown()),
  z.array(z.unknown()),
  z.string(),
  z.number(),
  z.boolean(),
  z.null(),
]);

export const ProductAttributeSchema = z.object({
  id: z.string().uuid(),
  variant_id: z.string().uuid().nullable(),
  key: z.string().min(1),
  value: CatalogJsonValueSchema,
  value_type: z.string().min(1),
  unit: z.string().nullable(),
  locale: z.string().nullable(),
  value_state: z.enum([
    "present",
    "missing",
    "unknown",
    "not_applicable",
    "conflicting",
  ]),
  transformer_version: z.string().nullable(),
  confidence: z.enum(["high", "medium", "low"]),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const ProductImageSchema = z.object({
  id: z.string().uuid(),
  variant_id: z.string().uuid().nullable(),
  url: z.string().url(),
  alt_text: z.string().nullable(),
  position: z.number().int().nonnegative(),
  checksum: z.string().nullable(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const ProductVariantSchema = z.object({
  id: z.string().uuid(),
  canonical_key: z.string().min(1),
  sku: z.string().nullable(),
  title: z.string().nullable(),
  option_values: z.record(z.string(), z.unknown()),
  is_retired: z.boolean(),
  attributes: z.array(ProductAttributeSchema),
  images: z.array(ProductImageSchema),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const ProductListItemSchema = z.object({
  id: z.string().uuid(),
  canonical_key: z.string().min(1),
  title: z.string().min(1),
  primary_category_id: z.string().uuid().nullable(),
  status: z.string().min(1),
  variant_count: z.number().int().nonnegative(),
  attribute_count: z.number().int().nonnegative(),
  image_count: z.number().int().nonnegative(),
  warning_count: z.number().int().nonnegative(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const ProductListResponseSchema = z.object({
  items: z.array(ProductListItemSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(100),
  offset: z.number().int().nonnegative(),
}).strict();

export const ProductDetailSchema = z.object({
  id: z.string().uuid(),
  workspace_id: z.string().uuid(),
  canonical_key: z.string().min(1),
  title: z.string().min(1),
  primary_category_id: z.string().uuid().nullable(),
  status: z.string().min(1),
  product_attributes: z.array(ProductAttributeSchema),
  product_images: z.array(ProductImageSchema),
  variants: z.array(ProductVariantSchema),
  warning_count: z.number().int().nonnegative(),
  provenance_count: z.number().int().nonnegative(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const EvidenceReferenceSchema = z.object({
  id: z.string().uuid(),
  source_record_id: z.string().uuid(),
  catalog_source_id: z.string().uuid(),
  catalog_source_name: z.string().min(1),
  source_type: z.string().min(1),
  external_id: z.string().min(1),
  source_updated_at: z.string().datetime().nullable(),
  snapshot_at: z.string().datetime(),
  product_id: z.string().uuid().nullable(),
  variant_id: z.string().uuid().nullable(),
  attribute_id: z.string().uuid().nullable(),
  attribute_key: z.string().nullable(),
  field_path: z.string().min(1),
  excerpt: z.string().nullable(),
  checksum: z.string().length(64),
  created_at: z.string().datetime(),
}).strict();

export const ProductProvenanceResponseSchema = z.object({
  product_id: z.string().uuid(),
  items: z.array(EvidenceReferenceSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(200),
  offset: z.number().int().nonnegative(),
}).strict();

export const IdentityProductSummarySchema = z.object({
  id: z.string().uuid(),
  canonical_key: z.string().min(1),
  title: z.string().min(1),
  status: z.string().min(1),
}).strict();

export const IdentitySignalSchema = z.object({
  kind: z.string().min(1).max(80),
  value: z.string().max(500).nullable(),
  weight_basis_points: z.number().int().min(0).max(10000),
}).strict();

export const ProductIdentityCandidateSchema = z.object({
  id: z.string().uuid(),
  left_product: IdentityProductSummarySchema,
  right_product: IdentityProductSummarySchema,
  match_type: z.enum(["deterministic", "fuzzy"]),
  score_basis_points: z.number().int().min(0).max(10000),
  signals: z.array(IdentitySignalSchema),
  algorithm_version: z.string().min(1),
  status: z.enum(["pending", "accepted", "rejected", "superseded"]),
  resolved_by_user_id: z.string().uuid().nullable(),
  resolved_at: z.string().datetime().nullable(),
  resolution_reason: z.string().nullable(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const ProductIdentityCandidateListResponseSchema = z.object({
  items: z.array(ProductIdentityCandidateSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(200),
  offset: z.number().int().nonnegative(),
}).strict();

export const IdentityCandidateRefreshResponseSchema = z.object({
  products_considered: z.number().int().nonnegative(),
  candidates_created: z.number().int().nonnegative(),
  candidates_updated: z.number().int().nonnegative(),
  candidates_superseded: z.number().int().nonnegative(),
  truncated: z.boolean(),
  algorithm_version: z.string().min(1),
}).strict();

export const ProductIdentityMemberSchema = z.object({
  product: IdentityProductSummarySchema,
  linked_by_user_id: z.string().uuid().nullable(),
  link_reason: z.string().min(1),
  linked_at: z.string().datetime(),
}).strict();

export const ProductIdentitySchema = z.object({
  identity_id: z.string().uuid(),
  status: z.enum(["active", "dissolved"]),
  members: z.array(ProductIdentityMemberSchema),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
}).strict();

export const UnlinkProductResponseSchema = z.object({
  identity_id: z.string().uuid(),
  product_id: z.string().uuid(),
  dissolved: z.boolean(),
}).strict();

export type ProductAttribute = z.infer<typeof ProductAttributeSchema>;
export type ProductImage = z.infer<typeof ProductImageSchema>;
export type ProductVariant = z.infer<typeof ProductVariantSchema>;
export type ProductListItem = z.infer<typeof ProductListItemSchema>;
export type ProductListResponse = z.infer<typeof ProductListResponseSchema>;
export type ProductDetail = z.infer<typeof ProductDetailSchema>;
export type EvidenceReference = z.infer<typeof EvidenceReferenceSchema>;
export type ProductProvenanceResponse = z.infer<
  typeof ProductProvenanceResponseSchema
>;
export type IdentityProductSummary = z.infer<typeof IdentityProductSummarySchema>;
export type IdentitySignal = z.infer<typeof IdentitySignalSchema>;
export type ProductIdentityCandidate = z.infer<typeof ProductIdentityCandidateSchema>;
export type ProductIdentityCandidateListResponse = z.infer<
  typeof ProductIdentityCandidateListResponseSchema
>;
export type IdentityCandidateRefreshResponse = z.infer<
  typeof IdentityCandidateRefreshResponseSchema
>;
export type ProductIdentity = z.infer<typeof ProductIdentitySchema>;
export type UnlinkProductResponse = z.infer<typeof UnlinkProductResponseSchema>;
