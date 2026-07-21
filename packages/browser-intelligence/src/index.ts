export type BrowserIntelligenceCapabilities = {
  webGpu: boolean;
  webAssembly: boolean;
  preferredDevice: "webgpu" | "wasm" | "unavailable";
};

export function detectBrowserIntelligenceCapabilities(): BrowserIntelligenceCapabilities {
  const webGpu = typeof navigator !== "undefined" && "gpu" in navigator;
  const webAssembly = typeof WebAssembly !== "undefined";
  return {
    webGpu,
    webAssembly,
    preferredDevice: webGpu ? "webgpu" : webAssembly ? "wasm" : "unavailable",
  };
}

export type EmbedTextOptions = {
  model?: string;
  device?: "webgpu" | "wasm";
  transformersModuleUrl?: string;
};

type TensorLike = { tolist(): unknown };
type FeatureExtractor = (
  texts: string[],
  options: { pooling: "mean"; normalize: true },
) => Promise<TensorLike>;
type TransformersModule = {
  pipeline(
    task: "feature-extraction",
    model: string,
    options: { device: "webgpu" | "wasm" },
  ): Promise<FeatureExtractor>;
};

/** Runs open-source text embedding locally in the browser. */
export async function embedTextLocally(
  texts: string[],
  options: EmbedTextOptions = {},
): Promise<number[][]> {
  if (typeof window === "undefined") {
    throw new Error("Browser-side intelligence can only execute in a browser context.");
  }
  if (texts.length === 0) return [];

  const capabilities = detectBrowserIntelligenceCapabilities();
  if (capabilities.preferredDevice === "unavailable") {
    throw new Error("This browser does not provide WebGPU or WebAssembly inference support.");
  }

  const moduleUrl =
    options.transformersModuleUrl ??
    "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.2.0/+esm";
  const dynamicImport = new Function("url", "return import(url)") as (
    url: string,
  ) => Promise<TransformersModule>;
  const { pipeline } = await dynamicImport(moduleUrl);
  const device = options.device ?? (capabilities.webGpu ? "webgpu" : "wasm");
  const extractor = await pipeline(
    "feature-extraction",
    options.model ?? "mixedbread-ai/mxbai-embed-xsmall-v1",
    { device },
  );
  const output = await extractor(texts, { pooling: "mean", normalize: true });
  return output.tolist() as number[][];
}
