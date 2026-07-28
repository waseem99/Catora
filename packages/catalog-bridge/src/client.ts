import {
  CATALOG_BRIDGE_MAX_BATCH_RECORDS,
  CATALOG_BRIDGE_PROTOCOL_VERSION,
  CatalogBridgeBatchSchema,
  CatalogBridgeCompleteRequestSchema,
  CatalogBridgeProductSchema,
  CatalogBridgeSnapshotManifestSchema,
  CatalogBridgeSnapshotStatusSchema,
  type CatalogBridgeProduct,
  type CatalogBridgeSnapshotStatus,
} from "@catora/contracts";
import { createHash, createHmac, randomUUID } from "node:crypto";

export interface CatalogBridgeCredentials {
  endpoint: string;
  sourceId: string;
  token: string;
}

export interface CatalogBridgeCheckpoint {
  snapshotId: string;
  nextSequence: number;
}

export interface CatalogBridgeCheckpointStore {
  load(): Promise<CatalogBridgeCheckpoint | null>;
  save(checkpoint: CatalogBridgeCheckpoint): Promise<void>;
  clear(): Promise<void>;
}

export type CatalogBridgeProgress =
  | { stage: "validating"; processedProducts: number }
  | { stage: "uploading"; uploadedProducts: number; uploadedBatches: number }
  | { stage: "queued"; status: CatalogBridgeSnapshotStatus };

export interface UploadCatalogSnapshotInput {
  products: Iterable<CatalogBridgeProduct> | AsyncIterable<CatalogBridgeProduct>;
  productCount: number;
  variantCount: number;
  sourceLabel?: string;
  metadata?: Record<string, string>;
  snapshotId?: string;
}

export interface CatalogBridgeClientOptions extends CatalogBridgeCredentials {
  batchSize?: number;
  maxAttempts?: number;
  retryBaseDelayMs?: number;
  fetchImplementation?: typeof fetch;
  checkpointStore?: CatalogBridgeCheckpointStore;
  onProgress?: (progress: CatalogBridgeProgress) => void;
}

export class CatalogBridgeError extends Error {
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(message: string, options?: { status?: number; retryable?: boolean }) {
    super(message);
    this.name = "CatalogBridgeError";
    this.status = options?.status ?? null;
    this.retryable = options?.retryable ?? false;
  }
}

type JsonCompatible =
  | null
  | boolean
  | number
  | string
  | JsonCompatible[]
  | { [key: string]: JsonCompatible | undefined };

function sortedJsonValue(value: JsonCompatible): JsonCompatible {
  if (Array.isArray(value)) {
    return value.map((item) => sortedJsonValue(item));
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right));
    return Object.fromEntries(
      entries.map(([key, item]) => [key, sortedJsonValue(item as JsonCompatible)]),
    );
  }
  return value;
}

export function canonicalJson(value: JsonCompatible): string {
  return JSON.stringify(sortedJsonValue(value));
}

export function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

export function signCatalogBridgeRequest(input: {
  method: string;
  path: string;
  timestamp: string;
  contentSha256: string;
  idempotencyKey: string;
  token: string;
}): string {
  const canonical = [
    input.method.toUpperCase(),
    input.path,
    input.timestamp,
    input.contentSha256,
    input.idempotencyKey,
  ].join("\n");
  return createHmac("sha256", input.token).update(canonical).digest("base64url");
}

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

export class CatalogBridgeClient {
  private readonly endpoint: string;
  private readonly sourceId: string;
  private readonly token: string;
  private readonly batchSize: number;
  private readonly maxAttempts: number;
  private readonly retryBaseDelayMs: number;
  private readonly fetchImplementation: typeof fetch;
  private readonly checkpointStore: CatalogBridgeCheckpointStore | undefined;
  private readonly onProgress: ((progress: CatalogBridgeProgress) => void) | undefined;

  constructor(options: CatalogBridgeClientOptions) {
    const endpoint = new URL(options.endpoint);
    if (endpoint.protocol !== "https:" && endpoint.hostname !== "localhost") {
      throw new CatalogBridgeError("Catalog bridge endpoint must use HTTPS outside localhost");
    }
    if (!options.sourceId || !options.token) {
      throw new CatalogBridgeError("Catalog bridge source ID and token are required");
    }
    const batchSize = options.batchSize ?? 100;
    if (batchSize < 1 || batchSize > CATALOG_BRIDGE_MAX_BATCH_RECORDS) {
      throw new CatalogBridgeError(
        `batchSize must be between 1 and ${CATALOG_BRIDGE_MAX_BATCH_RECORDS}`,
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
    input: UploadCatalogSnapshotInput,
  ): Promise<CatalogBridgeSnapshotStatus> {
    if (!Number.isInteger(input.productCount) || input.productCount < 0) {
      throw new CatalogBridgeError("productCount must be a non-negative integer");
    }
    if (!Number.isInteger(input.variantCount) || input.variantCount < 0) {
      throw new CatalogBridgeError("variantCount must be a non-negative integer");
    }

    const storedCheckpoint = await this.checkpointStore?.load();
    const snapshotId = input.snapshotId ?? storedCheckpoint?.snapshotId ?? randomUUID();
    let nextSequence =
      storedCheckpoint?.snapshotId === snapshotId ? storedCheckpoint.nextSequence : 0;

    const manifest = CatalogBridgeSnapshotManifestSchema.parse({
      protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
      snapshotId,
      startedAt: new Date().toISOString(),
      declaredProductCount: input.productCount,
      declaredVariantCount: input.variantCount,
      sourceLabel: input.sourceLabel,
      metadata: input.metadata,
    });
    await this.request(
      "POST",
      `/api/v1/catalog-bridge/sources/${this.sourceId}/snapshots`,
      manifest,
      `${snapshotId}:manifest`,
    );

    let processedProducts = 0;
    let uploadedProducts = 0;
    let uploadedBatches = 0;
    let observedVariants = 0;
    let batch: CatalogBridgeProduct[] = [];

    const flush = async (): Promise<void> => {
      if (batch.length === 0) {
        return;
      }
      const sequence = uploadedBatches;
      const records = batch;
      batch = [];
      if (sequence >= nextSequence) {
        const payload = CatalogBridgeBatchSchema.parse({
          protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
          snapshotId,
          sequence,
          records,
        });
        const body = canonicalJson(payload);
        await this.request(
          "PUT",
          `/api/v1/catalog-bridge/sources/${this.sourceId}/snapshots/${snapshotId}/batches/${sequence}`,
          payload,
          `${snapshotId}:batch:${sequence}:${sha256(body)}`,
        );
        nextSequence = sequence + 1;
        await this.checkpointStore?.save({ snapshotId, nextSequence });
      }
      uploadedProducts += records.length;
      uploadedBatches += 1;
      this.onProgress?.({ stage: "uploading", uploadedProducts, uploadedBatches });
    };

    for await (const candidate of toAsyncIterable(input.products)) {
      const product = CatalogBridgeProductSchema.parse(candidate);
      processedProducts += 1;
      observedVariants += product.variants?.length ?? 0;
      this.onProgress?.({ stage: "validating", processedProducts });
      batch.push(product);
      if (batch.length >= this.batchSize) {
        await flush();
      }
    }
    await flush();

    if (processedProducts !== input.productCount) {
      throw new CatalogBridgeError(
        `Declared ${input.productCount} products but mapped ${processedProducts}`,
      );
    }
    if (observedVariants !== input.variantCount) {
      throw new CatalogBridgeError(
        `Declared ${input.variantCount} variants but mapped ${observedVariants}`,
      );
    }

    const complete = CatalogBridgeCompleteRequestSchema.parse({
      protocolVersion: CATALOG_BRIDGE_PROTOCOL_VERSION,
      snapshotId,
      batchCount: uploadedBatches,
      productCount: processedProducts,
      variantCount: observedVariants,
    });
    const status = CatalogBridgeSnapshotStatusSchema.parse(
      await this.request(
        "POST",
        `/api/v1/catalog-bridge/sources/${this.sourceId}/snapshots/${snapshotId}/complete`,
        complete,
        `${snapshotId}:complete`,
      ),
    );
    await this.checkpointStore?.clear();
    this.onProgress?.({ stage: "queued", status });
    return status;
  }

  async snapshotStatus(snapshotId: string): Promise<CatalogBridgeSnapshotStatus> {
    return CatalogBridgeSnapshotStatusSchema.parse(
      await this.request(
        "GET",
        `/api/v1/catalog-bridge/sources/${this.sourceId}/snapshots/${snapshotId}`,
        undefined,
        `${snapshotId}:status`,
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
            : `Catalog bridge request failed with status ${response.status}`;
        lastError = new CatalogBridgeError(detail, {
          status: response.status,
          retryable,
        });
      } catch (error) {
        lastError =
          error instanceof CatalogBridgeError
            ? error
            : new CatalogBridgeError("Catalog bridge request failed", {
                retryable: true,
              });
      }

      if (!lastError.retryable || attempt === this.maxAttempts) {
        throw lastError;
      }
      const retryAfter = this.retryBaseDelayMs * 2 ** (attempt - 1);
      await wait(retryAfter + Math.floor(Math.random() * 100));
    }
    throw lastError ?? new CatalogBridgeError("Catalog bridge request failed");
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
