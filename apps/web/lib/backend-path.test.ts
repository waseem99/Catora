import { describe, expect, it } from "vitest";
import { backendApiPath } from "./backend-path";

describe("backendApiPath", () => {
  it("routes API paths through the same-origin runtime proxy", () => {
    expect(backendApiPath("/api/v1/auth/me")).toBe("/api/backend/api/v1/auth/me");
  });

  it("rejects non-absolute backend paths", () => {
    expect(() => backendApiPath("api/v1/auth/me")).toThrow(
      "Backend API path must start with /",
    );
  });
});
