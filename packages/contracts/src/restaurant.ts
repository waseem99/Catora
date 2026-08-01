import { z } from "zod";

import { CatalogBridgeJsonValueSchema } from "./catalog-bridge";

export const RESTAURANT_DOMAIN_VERSION = "restaurant-domain/v1" as const;

export const RestaurantFactStateSchema = z.enum([
  "supported",
  "partial",
  "unsupported",
  "stale",
  "conflicting",
  "inaccessible",
]);

export const RestaurantConfidenceSchema = z.enum(["high", "medium", "low"]);

export const RestaurantAvailabilityStateSchema = z.enum([
  "available",
  "unavailable",
  "unknown",
  "not_applicable",
  "conflicting",
  "stale",
]);

export const RestaurantAddressSchema = z
  .object({
    streetAddress: z.string().max(500).nullable().optional(),
    addressLocality: z.string().max(200).nullable().optional(),
    addressRegion: z.string().max(200).nullable().optional(),
    postalCode: z.string().max(50).nullable().optional(),
    addressCountry: z.string().max(100).nullable().optional(),
  })
  .strict();

export const RestaurantGeoCoordinatesSchema = z
  .object({
    latitude: z.number().min(-90).max(90),
    longitude: z.number().min(-180).max(180),
  })
  .strict();

export const RestaurantOpeningHoursIntervalSchema = z
  .object({
    dayOfWeek: z.enum([
      "monday",
      "tuesday",
      "wednesday",
      "thursday",
      "friday",
      "saturday",
      "sunday",
    ]),
    opens: z.string().min(1).max(20),
    closes: z.string().min(1).max(20),
  })
  .strict();

export const RestaurantSpecialHoursIntervalSchema = z
  .object({
    startsAt: z.string().datetime(),
    endsAt: z.string().datetime(),
    opens: z.string().min(1).max(20).nullable().optional(),
    closes: z.string().min(1).max(20).nullable().optional(),
    closed: z.boolean().default(false),
  })
  .strict()
  .superRefine((interval, context) => {
    if (Date.parse(interval.endsAt) <= Date.parse(interval.startsAt)) {
      context.addIssue({
        code: "custom",
        path: ["endsAt"],
        message: "endsAt must be after startsAt",
      });
    }
    if (interval.closed && (interval.opens || interval.closes)) {
      context.addIssue({
        code: "custom",
        path: ["closed"],
        message: "Closed special hours cannot define opening times",
      });
    }
  });

export const RestaurantFactSchema = z
  .object({
    key: z.string().min(1).max(160),
    value: CatalogBridgeJsonValueSchema.nullable().optional(),
    valueType: z.string().min(1).max(50),
    state: RestaurantFactStateSchema,
    confidence: RestaurantConfidenceSchema.default("high"),
    sourceRecordId: z.string().uuid(),
    fieldPath: z.string().min(1).max(500),
    observedAt: z.string().datetime(),
    effectiveAt: z.string().datetime().nullable().optional(),
    expiresAt: z.string().datetime().nullable().optional(),
    invalidatedAt: z.string().datetime().nullable().optional(),
    unit: z.string().max(30).nullable().optional(),
    locale: z.string().max(35).nullable().optional(),
    checksum: z.string().regex(/^[0-9a-f]{64}$/),
    policyVersion: z.string().max(100).nullable().optional(),
  })
  .strict()
  .superRefine((fact, context) => {
    if (fact.state === "supported" && fact.value == null) {
      context.addIssue({
        code: "custom",
        path: ["value"],
        message: "Supported facts require a value",
      });
    }
    if (fact.expiresAt && Date.parse(fact.expiresAt) < Date.parse(fact.observedAt)) {
      context.addIssue({
        code: "custom",
        path: ["expiresAt"],
        message: "expiresAt cannot precede observedAt",
      });
    }
    if (
      fact.invalidatedAt &&
      Date.parse(fact.invalidatedAt) < Date.parse(fact.observedAt)
    ) {
      context.addIssue({
        code: "custom",
        path: ["invalidatedAt"],
        message: "invalidatedAt cannot precede observedAt",
      });
    }
  });

export const RestaurantFreshnessPolicySchema = z
  .object({
    entityType: z.enum([
      "brand",
      "location",
      "service_area",
      "menu",
      "menu_item",
      "offer",
    ]),
    factKey: z.string().min(1).max(160),
    warningAgeSeconds: z.number().int().nonnegative(),
    maxAgeSeconds: z.number().int().positive(),
    policyVersion: z.string().min(1).max(100),
    rationale: z.string().max(2_000).nullable().optional(),
  })
  .strict()
  .superRefine((policy, context) => {
    if (policy.maxAgeSeconds <= policy.warningAgeSeconds) {
      context.addIssue({
        code: "custom",
        path: ["maxAgeSeconds"],
        message: "maxAgeSeconds must exceed warningAgeSeconds",
      });
    }
  });

export const RestaurantIdentityAliasSchema = z
  .object({
    alias: z.string().min(1).max(500),
    normalizedAlias: z.string().min(1).max(500),
    sourceRecordId: z.string().uuid().nullable().optional(),
  })
  .strict();

export const RestaurantServiceAreaSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    label: z.string().min(1).max(500),
    areaType: z.enum([
      "city",
      "district",
      "neighborhood",
      "postal_code",
      "polygon",
      "radius",
    ]),
    geometry: z.record(z.string(), CatalogBridgeJsonValueSchema).default({}),
    orderingUrl: z.string().url().nullable().optional(),
    status: z.enum(["active", "inactive", "retired"]).default("active"),
  })
  .strict();

const MoneyValueSchema = z.string().regex(/^-?\d+(\.\d{1,6})?$/);

export const RestaurantModifierOptionSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    priceDelta: MoneyValueSchema.nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    availabilityState: z
      .enum(["available", "unavailable", "unknown", "stale"])
      .default("unknown"),
    position: z.number().int().nonnegative().default(0),
  })
  .strict();

export const RestaurantModifierGroupSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    required: z.boolean().default(false),
    minSelections: z.number().int().nonnegative().default(0),
    maxSelections: z.number().int().nonnegative().default(1),
    position: z.number().int().nonnegative().default(0),
    options: z.array(RestaurantModifierOptionSchema).max(500).default([]),
  })
  .strict()
  .superRefine((group, context) => {
    if (group.maxSelections < group.minSelections) {
      context.addIssue({
        code: "custom",
        path: ["maxSelections"],
        message: "maxSelections cannot be less than minSelections",
      });
    }
    const keys = new Set<string>();
    for (const [index, option] of group.options.entries()) {
      if (keys.has(option.canonicalKey)) {
        context.addIssue({
          code: "custom",
          path: ["options", index, "canonicalKey"],
          message: "Modifier option canonical keys must be unique",
        });
      }
      keys.add(option.canonicalKey);
    }
  });

export const RestaurantMenuItemSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    description: z.string().max(100_000).nullable().optional(),
    priceAmount: MoneyValueSchema.nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    dietaryFacts: z
      .record(z.string().min(1).max(160), CatalogBridgeJsonValueSchema)
      .default({}),
    allergenFacts: z
      .record(z.string().min(1).max(160), CatalogBridgeJsonValueSchema)
      .default({}),
    availabilityState: RestaurantAvailabilityStateSchema.default("unknown"),
    status: z.enum(["active", "inactive", "retired"]).default("active"),
    sourceUpdatedAt: z.string().datetime().nullable().optional(),
    modifiers: z.array(RestaurantModifierGroupSchema).max(100).default([]),
    facts: z.array(RestaurantFactSchema).max(500).default([]),
  })
  .strict();

export const RestaurantMenuSectionSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    description: z.string().max(20_000).nullable().optional(),
    position: z.number().int().nonnegative().default(0),
    items: z.array(RestaurantMenuItemSchema).max(5_000).default([]),
  })
  .strict();

export const RestaurantMenuSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    description: z.string().max(20_000).nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    status: z.enum(["active", "inactive", "retired"]).default("active"),
    availableFrom: z.string().datetime().nullable().optional(),
    availableUntil: z.string().datetime().nullable().optional(),
    sourceUpdatedAt: z.string().datetime().nullable().optional(),
    sections: z.array(RestaurantMenuSectionSchema).max(500).default([]),
    facts: z.array(RestaurantFactSchema).max(500).default([]),
  })
  .strict();

export const RestaurantOfferOrPromotionSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    description: z.string().max(20_000).nullable().optional(),
    startsAt: z.string().datetime().nullable().optional(),
    endsAt: z.string().datetime().nullable().optional(),
    status: z
      .enum(["scheduled", "active", "expired", "cancelled", "unknown"])
      .default("unknown"),
    facts: z.array(RestaurantFactSchema).max(500).default([]),
  })
  .strict();

export const RestaurantLocationProjectionSchema = z
  .object({
    canonicalKey: z.string().min(1).max(500),
    externalLocationId: z.string().max(500).nullable().optional(),
    name: z.string().min(1).max(500),
    phone: z.string().max(100).nullable().optional(),
    websiteUrl: z.string().url().nullable().optional(),
    orderingUrl: z.string().url().nullable().optional(),
    address: RestaurantAddressSchema.default({}),
    geo: RestaurantGeoCoordinatesSchema.nullable().optional(),
    regularHours: z.array(RestaurantOpeningHoursIntervalSchema).max(100).default([]),
    specialHours: z.array(RestaurantSpecialHoursIntervalSchema).max(500).default([]),
    serviceModes: z
      .array(
        z.enum([
          "dine_in",
          "takeaway",
          "drive_through",
          "delivery",
          "curbside",
          "catering",
        ]),
      )
      .max(20)
      .default([]),
    facilities: z.array(z.string().min(1).max(200)).max(200).default([]),
    cuisineTypes: z.array(z.string().min(1).max(200)).max(100).default([]),
    aliases: z.array(RestaurantIdentityAliasSchema).max(500).default([]),
    serviceAreas: z.array(RestaurantServiceAreaSchema).max(1_000).default([]),
    menus: z.array(RestaurantMenuSchema).max(100).default([]),
    offers: z.array(RestaurantOfferOrPromotionSchema).max(1_000).default([]),
    facts: z.array(RestaurantFactSchema).max(2_000).default([]),
    status: z
      .enum(["active", "temporarily_closed", "inactive", "retired"])
      .default("active"),
  })
  .strict();

export const RestaurantBrandProjectionSchema = z
  .object({
    version: z.literal(RESTAURANT_DOMAIN_VERSION),
    canonicalKey: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    legalName: z.string().max(500).nullable().optional(),
    websiteUrl: z.string().url().nullable().optional(),
    aliases: z.array(RestaurantIdentityAliasSchema).max(500).default([]),
    locations: z.array(RestaurantLocationProjectionSchema).max(10_000).default([]),
    offers: z.array(RestaurantOfferOrPromotionSchema).max(10_000).default([]),
    facts: z.array(RestaurantFactSchema).max(5_000).default([]),
    status: z.enum(["active", "inactive", "retired"]).default("active"),
  })
  .strict();

export const RestaurantSnapshotSchema = z
  .object({
    version: z.literal(RESTAURANT_DOMAIN_VERSION),
    sourceId: z.string().uuid(),
    snapshotId: z.string().uuid(),
    observedAt: z.string().datetime(),
    brands: z.array(RestaurantBrandProjectionSchema).min(1).max(1_000),
  })
  .strict();

export type RestaurantFactState = z.infer<typeof RestaurantFactStateSchema>;
export type RestaurantFact = z.infer<typeof RestaurantFactSchema>;
export type RestaurantFreshnessPolicy = z.infer<
  typeof RestaurantFreshnessPolicySchema
>;
export type RestaurantMenuItem = z.infer<typeof RestaurantMenuItemSchema>;
export type RestaurantMenu = z.infer<typeof RestaurantMenuSchema>;
export type RestaurantLocationProjection = z.infer<
  typeof RestaurantLocationProjectionSchema
>;
export type RestaurantBrandProjection = z.infer<
  typeof RestaurantBrandProjectionSchema
>;
export type RestaurantSnapshot = z.infer<typeof RestaurantSnapshotSchema>;
