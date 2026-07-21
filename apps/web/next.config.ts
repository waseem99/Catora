import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@catora/contracts", "@catora/browser-intelligence"],
  turbopack: {
    root: path.resolve(process.cwd(), "../.."),
  },
  experimental: {
    optimizePackageImports: ["@huggingface/transformers"],
  },
};

export default nextConfig;
