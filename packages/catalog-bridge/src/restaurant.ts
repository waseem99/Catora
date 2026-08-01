import {
  CATALOG_BRIDGE_PROTOCOL_VERSION,
  RESTAURANT_BRIDGE_MAX_BATCH_RECORDS,
  RESTAURANT_BRIDGE_PROFILE,
  RestaurantBridgeBatchSchema,
  RestaurantBridgeBrandSchema,
  RestaurantBridgeCompleteRequestSchema,
  RestaurantBridgeSnapshotManifestSchema,
  RestaurantBridgeSnapshotStatusSchema,
  type RestaurantBridgeBrand,
  type RestaurantBridgeSnapshotStatus,
} from "@catora/contracts";
import { randomUUID } from "node:crypto";

import {
  CatalogBridgeError,
  canonicalJson,
  sha256,
  signCatalogBridgeRequest,
  type CatalogBridgeCheckpoint,
  type CatalogBridgeCheckpointStore,
  type CatalogBridgeCredentials,
} from "./client.js";

export type RestaurantBridgeProgress =
  | { stage: "validating"; processedBrands: number }
  | { stage: "uploading"; uploadedBrands: number; uploadedBatches: number }
  | { stage: "queued"; status: RestaurantBridgeSnapshotStatus };

export interface UploadRestaurantSnapshotInput {
  brands: Iterable<RestaurantBridgeBrand> | AsyncIterable<RestaurantBridgeBrand>;
  brandCount: number;
  locationCount: number;
  menuItemCount: number;
  sourceLabel?: string;
  metadata?: Record<string, string>;
  snapshotId?: string;
}

export interface RestaurantBridgeClientOptions extends CatalogBridgeCredentials {
  batchSize?: number;
  maxAttempts?: number;
  retryBaseDelayMs?: number;
  fetchImplementation?: typeof fetch;
  checkpointStore?: CatalogBridgeCheckpointStore;
  onProgress?: (progress: RestaurantBridgeProgress) => void;
}

type JsonCompatible =
  | null
  | boolean
  | number
  | string
  | JsonCompatible[]
  | { [key: string]: JsonCompatible | undefined };

async function* toAsyncIterable<T>(
  input: Iterable<T> | AsyncIterable<T>,
): AsyncIterable<T> {
  if (Symbol.asyncIterator in input) {
    for await (const item of input as AsyncIterable<T>) {
      yield item;
    }
    return;
  }
  for (const item of input as Iterable<T>) {
    yield item;
  }
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

function nestedCounts(brand: RestaurantBridgeBrand): {
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

export class RestaurantCatalogBridgeClient {
  private readonly endpoint: string;
  private readonly sourceId: string;
  private readonly token: string;
  private readonly batchSize: number;
  private readonly maxAttempts: number;
  private readonly retryBaseDelayMs: number;
  private readonly fetchImplementation: typeof fetch;
  private readonly checkpointStore: CatalogBridgeCheckpointStore | undefined;
  private readonly onProgress: ((progress: RestaurantBridgeProgress) => void) | undefined;

  constructor(options: RestaurantBridgeClientOptions) {
    const endpoint = new URL(options.endpoint);
    if (endpoint.protocol !== "https:" && endpoint.hostname !== "localhost") {
      throw new CatalogBridgeError("Catalog bridge endpoint must use HTTPS outside localhost");
    }
    if (!options.sourceId || !options.token) {
      throw new CatalogBridgeError("Catalog bridge source ID and token are required");
    }
    const batchSize = options.batchSize ?? 25;
    if (batchSize < 1 || batchSize > RESTAURANT_BRIDGE_MAX_BATCH_RECORDS) {
      throw new CatalogBridgeError(
        `batchSize must be between 1 and ${RESTAURANT_BRIDGE_MAX_BATCH_RECORDS}`,
      );
    }
    this.endpoint = endpoint.toString().replace(/\/$/, "");
    this.sourceId = options.sourceId;
    this.token = options.token;
    this.batchSize = batchSize;
    this.maxAttempts = options.maxAttempts ?? 4;
    this.retryBaseDelayMs = options.retryBaseDelayMs ?? 500;
    this.fetchImplementation = options.fetchImplementation ?? fetch;
    this.checkpointStore = options.checkpointStore;
    this.onProgress = options.onProgress;
  }

  async uploadSnapshot(
    input: UploadRestaurantSnapshotInput,
  ): Promise<RestaurantBridgeSnapshotStatus> {
    for (const [name, value] of [
      ["brandCount", input.brandCount],
      ["locationCount", input.locationCount],
      ["menuItemCount", input.menuItemCount],
    ] as const) {
      if (!Number.isInteger(value) || value < 0) {
        throw new CatalogBridgeError(`${name} must be a non-negative integer`);
      }
    }
    const storedCheckpoint = await this.checkpointStore?.load();
    const snapshotId = input.snapshotId ?? storedCheckpoint?.snapshotId ?? randomUUID();
    let nextSequence =
      storedCheckpoint?.snapshotId === snapshotId ? storedCheckpoint.nextSequence : 0;
    const manifest = RestaurantBridgeSnapshotManifestSchema.parse({
      protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
      profile: RESTAURANT_BRIDGE_PROFILE,
      snapshotId,
      startedAt: new Date().toISOString(),
      declaredBrandCount: input.brandCount,
      declaredLocationCount: input.locationCount,
      declaredMenuItemCount: input.menuItemCount,
      sourceLabel: input.sourceLabel,
      metadata: input.metadata,
    });
    await this.request(
      "POST",
      `/api/v1/restaurant-bridge/sources/${this.sourceId}/snapshots`,
      manifest,
      `${snapshotId}:restaurant:manifest`,
    );

    let processedBrands = 0;
    let observedLocations = 0;
    let observedMenuItems = 0;
    let uploadedBrands = 0;
    let uploadedBatches = 0;
    let batch: RestaurantBridgeBrand[] = [];

    const flush = async (): Promise<void> => {
      if (batch.length === 0) {
        return;
      }
      const sequence = uploadedBatches;
      const records = batch;
      batch = [];
      if (sequence >= nextSequence) {
        const payload = RestaurantBridgeBatchSchema.parse({
          protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
          profile: RESTAURANT_BRIDGE_PROFILE,
          snapshotId,
          sequence,
          records,
        });
        const body = canonicalJson(payload);
        await this.request(
          "PUT",
          `/api/v1/restaurant-bridge/sources/${this.sourceId}/snapshots/${snapshotId}/batches/${sequence}`,
          payload,
          `${snapshotId}:restaurant:batch:${sequence}:${sha256(body)}`,
        );
        nextSequence = sequence + 1;
        await this.checkpointStore?.save({ snapshotId, nextSequence });
      }
      uploadedBrands += records.length;
      uploadedBatches += 1;
      this.onProgress?.({ stage: "uploading", uploadedBrands, uploadedBatches });
    };

    for await (const candidate of toAsyncIterable(input.brands)) {
      const brand = RestaurantBridgeBrandSchema.parse(candidate);
      const counts = nestedCounts(brand);
      processedBrands += 1;
      observedLocations += counts.locations;
      observedMenuItems += counts.menuItems;
      this.onProgress?.({ stage: "validating", processedBrands });
      batch.push(brand);
      if (batch.length >= this.batchSize) {
        await flush();
      }
    }
    await flush();

    if (processedBrands !== input.brandCount) {
      throw new CatalogBridgeError(
        `Declared ${input.brandCount} brands but mapped ${processedBrands}`,
      );
    }
    if (observedLocations !== input.locationCount) {
      throw new CatalogBridgeError(
        `Declared ${input.locationCount} locations but mapped ${observedLocations}`,
      );
    }
    if (observedMenuItems !== input.menuItemCount) {
      throw new CatalogBridgeError(
        `Declared ${input.menuItemCount} menu items but mapped ${observedMenuItems}`,
      );
    }

    const complete = RestaurantBridgeCompleteRequestSchema.parse({
      protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
      profile: RESTAURANT_BRIDGE_PROFILE,
      snapshotId,
      batchCount: uploadedBatches,
      brandCount: processedBrands,
      locationCount: observedLocations,
      menuItemCount: observedMenuItems,
    });
    const status = RestaurantBridgeSnapshotStatusSchema.parse(
      await this.request(
        "POST",
        `/api/v1/restaurant-bridge/sources/${this.sourceId}/snapshots/${snapshotId}/complete`,
        complete,
        `${snapshotId}:restaurant:complete`,
      ),
    );
    await this.checkpointStore?.clear();
    this.onProgress?.({ stage: "queued", status });
    return status;
  }

  async snapshotStatus(snapshotId: string): Promise<RestaurantBridgeSnapshotStatus> {
    return RestaurantBridgeSnapshotStatusSchema.parse(
      await this.request(
        "GET",
        `/api/v1/restaurant-bridge/sources/${this.sourceId}/snapshots/${snapshotId}`,
        undefined,
        `${snapshotId}:restaurant:status`,
      ),
    );
  }

  private async request(
    method: string,
    path: string,
    payload: JsonCompatible | undefined,
    idempotencyKey: string,
  ): Promise<unknown> {
    const body = payload === undefined ? "" : canonicalJson(payload);
    const contentSha256 = sha256(body);
    let lastError: CatalogBridgeError | null = null;
    for (let attempt = 1; attempt <= this.maxAttempts; attempt += 1) {
      const timestamp = Math.floor(Date.now() / 1_000).toString();
      const signature = signCatalogBridgeRequest({
        method,
        path,
        timestamp,
        contentSha256,
        idempotencyKey,
        token: this.token,
      });
      try {
        const response = await this.fetchImplementation(`${this.endpoint}${path}`, {
          method,
          headers: {
            accept: "application/json",
            "content-type": "application/json",
            "x-catora-content-sha256": contentSha256,
            "x-catora-idempotency-key": idempotencyKey,
            "x-catora-signature": signature,
            "x-catora-timestamp": timestamp,
          },
          body: body || undefined,
        });
        const responsePayload = await this.readResponse(response);
        if (response.ok) {
          return responsePayload;
        }
        const retryable =
          response.status === 408 || response.status === 429 || response.status >= 500;
        const detail =
          typeof responsePayload === "object" &&
          responsePayload !== null &&
          "detail" in responsePayload &&
          typeof responsePayload.detail === "string"
            ? responsePayload.detail
            : `Restaurant bridge request failed with status ${response.status}`;
        lastError = new CatalogBridgeError(detail, {
          status: response.status,
          retryable,
        });
      } catch (error) {
        lastError =
          error instanceof CatalogBridgeError
            ? error
            : new CatalogBridgeError("Restaurant bridge request failed", {
                retryable: true,
              });
      }
      if (!lastError.retryable || attempt === this.maxAttempts) {
        throw lastError;
      }
      await wait(this.retryBaseDelayMs * 2 ** (attempt - 1) + Math.floor(Math.random() * 100));
    }
    throw lastError ?? new CatalogBridgeError("Restaurant bridge request failed");
  }

  private async readResponse(response: Response): Promise<unknown> {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      return response.json();
    }
    const text = await response.text();
    return text ? { detail: text.slice(0, 500) } : {};
  }
}

export type { CatalogBridgeCheckpoint };
