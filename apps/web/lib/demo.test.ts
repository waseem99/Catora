import { describe, expect, it } from "vitest";
import { formatBasisPoints, humanizeStatus } from "./demo";

describe("demo formatting", () => {
  it("formats deterministic basis points", () => {
    expect(formatBasisPoints(6840)).toBe("68.4%");
  });

  it("humanizes persisted states", () => {
    expect(humanizeStatus("possible_match_missing_data")).toBe("possible match missing data");
  });
});
