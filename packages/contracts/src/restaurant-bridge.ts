import { z } from "zod";

import { CATALOG_BRIDGE_PROTOCOL_VERSION } from "./catalog-bridge";

export const RESTAURANT_BRIDGE_PROFILE = "restaurant/v1" as const;
export const RESTAURANT_BRIDGE_MAX_BATCH_RECORDS = 50;

const RestaurantBridgeAddressSchema = z
  .object({
    streetAddress: z.string().max(500).nullable().optional(),
    addressLocality: z.string().max(200).nullable().optional(),
    addressRegion: z.string().max(200).nullable().optional(),
    postalCode: z.string().max(50).nullable().optional(),
    addressCountry: z.string().max(100).nullable().optional(),
  })
  .strict();

const RestaurantBridgeGeoSchema = z
  .object({
    latitude: z.number().min(-90).max(90),
    longitude: z.number().min(-180).max(180),
  })
  .strict();

const RestaurantBridgeHoursSchema = z
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

const RestaurantBridgeSpecialHoursSchema = z
  .object({
    startsAt: z.string().datetime(),
    endsAt: z.string().datetime(),
    opens: z.string().min(1).max(20).nullable().optional(),
    closes: z.string().min(1).max(20).nullable().optional(),
    closed: z.boolean().default(false),
  })
  .strict()
  .superRefine((value, context) => {
    if (Date.parse(value.endsAt) <= Date.parse(value.startsAt)) {
      context.addIssue({
        code: "custom",
        path: ["endsAt"],
        message: "endsAt must be after startsAt",
      });
    }
    if (value.closed && (value.opens || value.closes)) {
      context.addIssue({
        code: "custom",
        path: ["closed"],
        message: "Closed special hours cannot define opening times",
      });
    }
  });

const RestaurantBridgeImageSchema = z
  .object({
    url: z.string().url().max(2_000),
    altText: z.string().max(1_000).nullable().optional(),
    position: z.number().int().nonnegative().max(10_000).default(0),
    checksum: z.string().regex(/^[0-9a-f]{64}$/).nullable().optional(),
  })
  .strict();

const RestaurantBridgeModifierOptionSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    priceDelta: z.number().finite().nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    availability: z.enum(["available", "unavailable", "unknown"]).default("unknown"),
    position: z.number().int().nonnegative().max(10_000).default(0),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict();

const RestaurantBridgeModifierGroupSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(500),
    required: z.boolean().default(false),
    minSelections: z.number().int().nonnegative().default(0),
    maxSelections: z.number().int().nonnegative().default(1),
    position: z.number().int().nonnegative().max(10_000).default(0),
    options: z.array(RestaurantBridgeModifierOptionSchema).max(500).default([]),
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
    const ids = new Set<string>();
    for (const [index, option] of group.options.entries()) {
      if (ids.has(option.id)) {
        context.addIssue({
          code: "custom",
          path: ["options", index, "id"],
          message: "Modifier option IDs must be unique inside a group",
        });
      }
      ids.add(option.id);
    }
  });

const SafeFactKeySchema = z
  .string()
  .min(1)
  .max(160)
  .refine(
    (value) =>
      !/(^|[_\-.])(cart|customer|order|payment|refund|loyalty|password|session|token|rider|driver)s?($|[_\-.])/i.test(
        value.replace(/([a-z0-9])([A-Z])/g, "$1_$2"),
      ),
    { message: "Restricted restaurant bridge field" },
  );

type RestaurantBridgeJsonValue =
  | string
  | number
  | boolean
  | null
  | RestaurantBridgeJsonValue[]
  | { [key: string]: RestaurantBridgeJsonValue };

const RestaurantBridgeJsonValueSchema: z.ZodType<RestaurantBridgeJsonValue> = z.lazy(() =>
  z.union([
    z.string().max(100_000),
    z.number().finite(),
    z.boolean(),
    z.null(),
    z.array(RestaurantBridgeJsonValueSchema).max(2_000),
    z.record(SafeFactKeySchema, RestaurantBridgeJsonValueSchema),
  ]),
);

const RestaurantBridgeMenuItemSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    description: z.string().max(100_000).nullable().optional(),
    price: z.number().finite().nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    availability: z.enum(["available", "unavailable", "unknown"]).default("unknown"),
    dietaryFacts: z
      .record(SafeFactKeySchema, RestaurantBridgeJsonValueSchema)
      .default({}),
    allergenFacts: z
      .record(SafeFactKeySchema, RestaurantBridgeJsonValueSchema)
      .default({}),
    images: z.array(RestaurantBridgeImageSchema).max(100).default([]),
    modifiers: z.array(RestaurantBridgeModifierGroupSchema).max(100).default([]),
    status: z.enum(["active", "inactive", "deleted"]).default("active"),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict()
  .superRefine((item, context) => {
    if (item.price != null && item.currency == null) {
      context.addIssue({
        code: "custom",
        path: ["currency"],
        message: "Menu item currency is required when price is present",
      });
    }
  });

const RestaurantBridgeMenuSectionSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    description: z.string().max(20_000).nullable().optional(),
    position: z.number().int().nonnegative().max(10_000).default(0),
    items: z.array(RestaurantBridgeMenuItemSchema).max(5_000).default([]),
  })
  .strict();

const RestaurantBridgeMenuSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    description: z.string().max(20_000).nullable().optional(),
    currency: z.string().length(3).nullable().optional(),
    status: z.enum(["active", "inactive", "deleted"]).default("active"),
    availableFrom: z.string().datetime().nullable().optional(),
    availableUntil: z.string().datetime().nullable().optional(),
    sections: z.array(RestaurantBridgeMenuSectionSchema).max(500).default([]),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict();

const RestaurantBridgeServiceAreaSchema = z
  .object({
    id: z.string().min(1).max(500),
    label: z.string().min(1).max(500),
    areaType: z.enum([
      "city",
      "district",
      "neighborhood",
      "postal_code",
      "polygon",
      "radius",
    ]),
    geometry: z.record(SafeFactKeySchema, RestaurantBridgeJsonValueSchema).default({}),
    orderingUrl: z.string().url().nullable().optional(),
    status: z.enum(["active", "inactive", "deleted"]).default("active"),
  })
  .strict();

const RestaurantBridgeLocationSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    aliases: z.array(z.string().min(1).max(500)).max(500).default([]),
    phone: z.string().max(100).nullable().optional(),
    websiteUrl: z.string().url().nullable().optional(),
    orderingUrl: z.string().url().nullable().optional(),
    address: RestaurantBridgeAddressSchema.default({}),
    geo: RestaurantBridgeGeoSchema.nullable().optional(),
    regularHours: z.array(RestaurantBridgeHoursSchema).max(100).default([]),
    specialHours: z.array(RestaurantBridgeSpecialHoursSchema).max(500).default([]),
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
    serviceAreas: z.array(RestaurantBridgeServiceAreaSchema).max(1_000).default([]),
    menus: z.array(RestaurantBridgeMenuSchema).max(100).default([]),
    status: z
      .enum(["active", "temporarily_closed", "inactive", "deleted"])
      .default("active"),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict();

const RestaurantBridgeOfferSchema = z
  .object({
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    description: z.string().max(20_000).nullable().optional(),
    locationIds: z.array(z.string().min(1).max(500)).max(10_000).default([]),
    menuItemIds: z.array(z.string().min(1).max(500)).max(10_000).default([]),
    startsAt: z.string().datetime().nullable().optional(),
    endsAt: z.string().datetime().nullable().optional(),
    status: z
      .enum(["scheduled", "active", "expired", "cancelled", "unknown"])
      .default("unknown"),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict()
  .superRefine((offer, context) => {
    if (offer.locationIds.length === 0 && offer.menuItemIds.length === 0) {
      context.addIssue({
        code: "custom",
        path: ["locationIds"],
        message: "Offer must reference at least one location or menu item",
      });
    }
  });

export const RestaurantBridgeBrandSchema = z
  .object({
    recordType: z.literal("restaurant_brand"),
    id: z.string().min(1).max(500),
    name: z.string().min(1).max(1_000),
    legalName: z.string().max(1_000).nullable().optional(),
    websiteUrl: z.string().url().nullable().optional(),
    aliases: z.array(z.string().min(1).max(500)).max(500).default([]),
    locations: z.array(RestaurantBridgeLocationSchema).min(1).max(10_000),
    offers: z.array(RestaurantBridgeOfferSchema).max(10_000).default([]),
    status: z.enum(["active", "inactive", "deleted"]).default("active"),
    updatedAt: z.string().datetime().nullable().optional(),
  })
  .strict();

export const RestaurantBridgeSnapshotManifestSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    profile: z.literal(RESTAURANT_BRIDGE_PROFILE),
    snapshotId: z.string().uuid(),
    startedAt: z.string().datetime(),
    declaredBrandCount: z.number().int().nonnegative(),
    declaredLocationCount: z.number().int().nonnegative(),
    declaredMenuItemCount: z.number().int().nonnegative(),
    sourceLabel: z.string().min(1).max(200).optional(),
    metadata: z.record(SafeFactKeySchema, z.string().max(500)).optional(),
  })
  .strict();

export const RestaurantBridgeBatchSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    profile: z.literal(RESTAURANT_BRIDGE_PROFILE),
    snapshotId: z.string().uuid(),
    sequence: z.number().int().nonnegative(),
    records: z
      .array(RestaurantBridgeBrandSchema)
      .min(1)
      .max(RESTAURANT_BRIDGE_MAX_BATCH_RECORDS),
  })
  .strict();

export const RestaurantBridgeCompleteRequestSchema = z
  .object({
    protocolVersion: z.literal(CATALOG_BRIDGE_PROTOCOL_VERSION),
    profile: z.literal(RESTAURANT_BRIDGE_PROFILE),
    snapshotId: z.string().uuid(),
    batchCount: z.number().int().positive(),
    brandCount: z.number().int().nonnegative(),
    locationCount: z.number().int().nonnegative(),
    menuItemCount: z.number().int().nonnegative(),
  })
  .strict();

export const RestaurantBridgeSnapshotStatusSchema = z
  .object({
    sourceId: z.string().uuid(),
    snapshotId: z.string().uuid(),
    profile: z.literal(RESTAURANT_BRIDGE_PROFILE),
    status: z.enum(["receiving", "queued", "processing", "completed", "failed"]),
    acceptedBatches: z.number().int().nonnegative(),
    acceptedBrands: z.number().int().nonnegative(),
    acceptedLocations: z.number().int().nonnegative(),
    acceptedMenuItems: z.number().int().nonnegative(),
    ingestionJobId: z.string().uuid().nullable(),
  })
  .strict();

export type RestaurantBridgeBrand = z.infer<typeof RestaurantBridgeBrandSchema>;
export type RestaurantBridgeBatch = z.infer<typeof RestaurantBridgeBatchSchema>;
export type RestaurantBridgeSnapshotManifest = z.infer<
  typeof RestaurantBridgeSnapshotManifestSchema
>;
export type RestaurantBridgeCompleteRequest = z.infer<
  typeof RestaurantBridgeCompleteRequestSchema
>;
export type RestaurantBridgeSnapshotStatus = z.infer<
  typeof RestaurantBridgeSnapshotStatusSchema
>;
