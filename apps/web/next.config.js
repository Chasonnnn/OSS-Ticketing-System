import path from "node:path"
import { fileURLToPath } from "node:url"

import { loadEnvConfig } from "@next/env"

// Load repo-root env so `apps/web` and `apps/api` can share one `.env` during local dev.
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const repoRoot = path.resolve(__dirname, "..", "..")
loadEnvConfig(repoRoot)

if (!process.env.NEXT_PUBLIC_API_BASE_URL && process.env.API_BASE_URL) {
  process.env.NEXT_PUBLIC_API_BASE_URL = process.env.API_BASE_URL
}

/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true
}

export default nextConfig
