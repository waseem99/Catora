import {
  RestaurantBridgeBrandSchema,
  type RestaurantBridgeBrand,
  type RestaurantBridgeSnapshotStatus,
} from "@catora/contracts";

import {
  RestaurantCatalogBridgeClient,
  type RestaurantBridgeClientOptions,
} from "./restaurant.js";

interface MongoQueryLike<T> {
  sort(value: Record<string, 1 | -1>): MongoQueryLike<T>;
  limit(value: number): MongoQueryLike<T>;
  lean(): MongoQueryLike<T>;
  exec(): Promise<T[]>;
}

export interface MongoRestaurantModelLike<T> {
  find(filter?: Record<string, unknown>): MongoQueryLike<T>;
}

export interface MongoRestaurantSourceOptions<T> {
  model: MongoRestaurantModelLike<T>;
  mapBrand: (document: T) => RestaurantBridgeBrand | Promise<RestaurantBridgeBrand>;
  filter?: Record<string, unknown>;
  pageSize?: number;
  cursorField?: string;
}

export interface MongoRestaurantInspection {
  brandCount: number;
  locationCount: number;
  menuItemCount: number;
  invalidCount: number;
  errors: Array<{ brand: string; message: string }>;
}

export interface RunMongoRestaurantBridgeOptions<T>
  extends
    MongoRestaurantSourceOptions<T>,
    Omit<RestaurantBridgeClientOptions, "onProgress"> {
  dryRun?: boolean;
  sourceLabel?: string;
  metadata?: Record<string, string>;
  maxValidationErrors?: number;
  onProgress?: RestaurantBridgeClientOptions["onProgress"];
}

export interface RunMongoRestaurantBridgeResult {
  inspection: MongoRestaurantInspection;
  status: RestaurantBridgeSnapshotStatus | null;
}

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

function pagedFilter(
  base: Record<string, unknown>,
  cursorField: string,
  cursor: unknown,
): Record<string, unknown> {
  if (cursor === undefined) {
    return base;
  }
  return { $and: [base, { [cursorField]: { $gt: cursor } }] };
}

function brandCounts(brand: RestaurantBridgeBrand): {
  locations: number;
  menuItems: number;
} {
  return {
    locations: brand.locations.length,
    menuItems: brand.locations.reduce(
      (locationTotal, location) =>
        locationTotal +
        location.menus.reduce(
          (menuTotal, menu) =>
            menuTotal +
            menu.sections.reduce(
              (sectionTotal, section) => sectionTotal + section.items.length,
              0,
            ),
          0,
        ),
      0,
    ),
  };
}

export async function* mongoRestaurantBrands<T>(
  options: MongoRestaurantSourceOptions<T>,
): AsyncIterable<RestaurantBridgeBrand> {
  const cursorField = options.cursorField ?? "_id";
  const pageSize = options.pageSize ?? 100;
  if (pageSize < 1 || pageSize > 1_000) {
    throw new Error("Restaurant bridge pageSize must be between 1 and 1000");
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
      const mapped = await options.mapBrand(document);
      yield RestaurantBridgeBrandSchema.parse(mapped);
    }
    const last = documents.at(-1);
    const nextCursor = readPath(last, cursorField);
    if (nextCursor === undefined || Object.is(nextCursor, cursor)) {
      throw new Error(
        `Restaurant bridge cursor field '${cursorField}' must be stable and present on every document`,
      );
    }
    cursor = nextCursor;
    if (documents.length < pageSize) {
      return;
    }
  }
}

export async function inspectMongoRestaurant<T>(
  options: MongoRestaurantSourceOptions<T>,
  maxErrors = 25,
): Promise<MongoRestaurantInspection> {
  let brandCount = 0;
  let locationCount = 0;
  let menuItemCount = 0;
  let invalidCount = 0;
  const errors: Array<{ brand: string; message: string }> = [];
  try {
    for await (const brand of mongoRestaurantBrands(options)) {
      const counts = brandCounts(brand);
      brandCount += 1;
      locationCount += counts.locations;
      menuItemCount += counts.menuItems;
    }
  } catch (error) {
    invalidCount += 1;
    if (errors.length < maxErrors) {
      errors.push({
        brand: "unknown",
        message: error instanceof Error ? error.message : "Restaurant mapping failed",
      });
    }
  }
  return { brandCount, locationCount, menuItemCount, invalidCount, errors };
}

export async function runMongoRestaurantBridge<T>(
  options: RunMongoRestaurantBridgeOptions<T>,
): Promise<RunMongoRestaurantBridgeResult> {
  const inspection = await inspectMongoRestaurant(
    options,
    options.maxValidationErrors ?? 25,
  );
  if (inspection.invalidCount > 0) {
    return { inspection, status: null };
  }
  if (options.dryRun) {
    return { inspection, status: null };
  }
  const client = new RestaurantCatalogBridgeClient({
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
    brands: mongoRestaurantBrands(options),
    brandCount: inspection.brandCount,
    locationCount: inspection.locationCount,
    menuItemCount: inspection.menuItemCount,
    sourceLabel: options.sourceLabel,
    metadata: options.metadata,
  });
  return { inspection, status };
}
