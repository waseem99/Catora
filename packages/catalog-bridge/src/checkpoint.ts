import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type {
  CatalogBridgeCheckpoint,
  CatalogBridgeCheckpointStore,
} from "./client.js";

export class FileCatalogBridgeCheckpointStore
  implements CatalogBridgeCheckpointStore
{
  constructor(private readonly path = ".catora/bridge-checkpoint.json") {}

  async load(): Promise<CatalogBridgeCheckpoint | null> {
    try {
      const content = await readFile(this.path, "utf8");
      const parsed = JSON.parse(content) as Partial<CatalogBridgeCheckpoint>;
      if (
        typeof parsed.snapshotId !== "string" ||
        typeof parsed.nextSequence !== "number" ||
        !Number.isInteger(parsed.nextSequence) ||
        parsed.nextSequence < 0
      ) {
        throw new Error("Catalog bridge checkpoint is invalid");
      }
      return {
        snapshotId: parsed.snapshotId,
        nextSequence: parsed.nextSequence,
      };
    } catch (error) {
      if (
        error &&
        typeof error === "object" &&
        "code" in error &&
        error.code === "ENOENT"
      ) {
        return null;
      }
      throw error;
    }
  }

  async save(checkpoint: CatalogBridgeCheckpoint): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.tmp`;
    await writeFile(temporary, `${JSON.stringify(checkpoint)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    await rename(temporary, this.path);
  }

  async clear(): Promise<void> {
    await rm(this.path, { force: true });
  }
}
