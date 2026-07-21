import { describe, expect, it } from "vitest";

import {
  catalogProductPath,
  catalogProductsPath,
  catalogProvenancePath,
  formatCatalogValue,
} from "./catalog";

const workspaceId = "22222222-2222-4222-8222-222222222222";
const productId = "11111111-1111-4111-8111-111111111111";

describe("catalog browser helpers", () => {
  it("builds bounded, encoded product queries", () => {
    const path = catalogProductsPath(workspaceId, {
      query: " Cloud & Sofa ",
      hasWarnings: true,
      limit: 25,
      offset: 50,
    });

    expect(path).toContain(`/api/v1/workspaces/${workspaceId}/products?`);
    expect(path).toContain("status=active");
    expect(path).toContain("query=Cloud+%26+Sofa");
    expect(path).toContain("has_warnings=true");
    expect(path).toContain("limit=25");
    expect(path).toContain("offset=50");
  });

  it("builds detail and provenance paths", () => {
    expect(catalogProductPath(workspaceId, productId)).toBe(
      `/api/v1/workspaces/${workspaceId}/products/${productId}`,
    );
    expect(catalogProvenancePath(workspaceId, productId)).toBe(
      `/api/v1/workspaces/${workspaceId}/products/${productId}/provenance`,
    );
  });

  it("formats scalar and structured values safely", () => {
    expect(formatCatalogValue(null)).toBe("—");
    expect(formatCatalogValue(true)).toBe("Yes");
    expect(formatCatalogValue(false)).toBe("No");
    expect(formatCatalogValue({ canonical_value: "2000", unit: "g" })).toContain(
      '"canonical_value": "2000"',
    );
  });
});
