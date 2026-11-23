import type { NextConfig } from "next";

// cacheComponents is intentionally left OFF (Next's default; not set here).
// The pages are force-dynamic, so every request gets fresh data. See README.
const nextConfig: NextConfig = {
  /* config options here */
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
