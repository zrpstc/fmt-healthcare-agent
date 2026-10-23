import { fileURLToPath } from "node:url";
import nextEnv from "@next/env";

// Load the repository environment for both `next build` and `next start`.
nextEnv.loadEnvConfig(fileURLToPath(new URL("../../", import.meta.url)));
const apiPort = process.env.WGS_API_PORT || "8503";
const proxyTimeout = Number(process.env.WGS_WEB_PROXY_TIMEOUT_MS || "900000");
if (!/^\d{1,5}$/.test(apiPort) || Number(apiPort) < 1 || Number(apiPort) > 65535) {
  throw new Error("WGS_API_PORT must be a port between 1 and 65535");
}
if (!Number.isInteger(proxyTimeout) || proxyTimeout < 30000 || proxyTimeout > 1800000) {
  throw new Error("WGS_WEB_PROXY_TIMEOUT_MS must be between 30000 and 1800000");
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.WGS_WEB_DIST_DIR || ".next",
  // Multi-section report narration can outlast Next's default 30-second proxy.
  experimental: { proxyTimeout },
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `http://127.0.0.1:${apiPort}/:path*` }];
  },
};
export default nextConfig;
