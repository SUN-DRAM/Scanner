import { describe, expect, it } from "vitest";

import robots from "./robots";

describe("robots.ts (Phase 2 Step 0.2)", () => {
  it("allows crawling and disallows only /api/, /admin/, /app/", () => {
    const result = robots();
    const rules = Array.isArray(result.rules) ? result.rules[0] : result.rules;

    expect(rules?.userAgent).toBe("*");
    expect(rules?.allow).toBe("/");
    expect(rules?.disallow).toEqual(["/api/", "/admin/", "/app/"]);
  });

  it("declares the sitemap", () => {
    const result = robots();
    expect(result.sitemap).toMatch(/\/sitemap\.xml$/);
  });
});
