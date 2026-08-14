import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The operator desk is intentionally opened at this loopback IP by Codex Desktop.
  // Without this explicit development allowlist, Next 16 blocks JS chunks with 403
  // and the server-rendered UI cannot hydrate or receive button events.
  allowedDevOrigins: ["127.0.0.1", "localhost"]
};

export default nextConfig;
