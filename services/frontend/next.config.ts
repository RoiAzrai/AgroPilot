import type { NextConfig } from "next";

// cacheComponents is intentionally left OFF (Next's default; not set here).
// The pages are force-dynamic, so every request gets fresh data. See README.
const nextConfig: NextConfig = {
  experimental: {
    serverActions: {
      // Photo upload: up to 5 MB of file plus multipart overhead. A bigger body throws
      // before the action runs, so the client checks the size before sending.
      bodySizeLimit: "6mb",
    },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
