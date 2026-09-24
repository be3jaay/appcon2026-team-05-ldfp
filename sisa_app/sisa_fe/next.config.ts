import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Standalone is only for the Docker image. Vercel packages the app itself,
  // and a standalone build there fails looking for .next/next-server.js.nft.json.
  output: process.env.VERCEL ? undefined : "standalone",
}

export default nextConfig
