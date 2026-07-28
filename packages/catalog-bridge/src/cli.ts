#!/usr/bin/env node

import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { runMongoCatalogBridge, type RunMongoCatalogBridgeOptions } from "./mongo.js";
import { FileCatalogBridgeCheckpointStore } from "./checkpoint.js";

function usage(): never {
  console.error(
    "Usage: catora-bridge <config.mjs> [--dry-run] [--checkpoint <path>]",
  );
  process.exit(2);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const configArgument = args.find((argument) => !argument.startsWith("--"));
  if (!configArgument) {
    usage();
  }
  const dryRun = args.includes("--dry-run");
  const checkpointIndex = args.indexOf("--checkpoint");
  const checkpointPath =
    checkpointIndex >= 0 ? args[checkpointIndex + 1] : undefined;
  if (checkpointIndex >= 0 && !checkpointPath) {
    usage();
  }

  const moduleUrl = pathToFileURL(resolve(configArgument)).href;
  const loaded = (await import(moduleUrl)) as {
    default?: RunMongoCatalogBridgeOptions<unknown>;
  };
  if (!loaded.default || typeof loaded.default !== "object") {
    throw new Error("Bridge config must export a default options object");
  }
  const config = loaded.default;
  const result = await runMongoCatalogBridge({
    ...config,
    dryRun,
    checkpointStore:
      config.checkpointStore ??
      new FileCatalogBridgeCheckpointStore(
        checkpointPath ?? ".catora/bridge-checkpoint.json",
      ),
    onProgress:
      config.onProgress ??
      ((progress) => {
        process.stderr.write(`${JSON.stringify(progress)}\n`);
      }),
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "Catalog bridge failed";
  console.error(message);
  process.exitCode = 1;
});
