import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const dirname = path.dirname(fileURLToPath(import.meta.url));

// Mirrors tsconfig.json's "@/*": ["./*"] — needed the moment a test imports
// a route module (page.tsx/generateMetadata) that itself pulls in "@/..."
// components or lib code, which robots.test.ts never needed to do.
export default defineConfig({
  resolve: {
    alias: {
      "@": dirname,
    },
  },
});
