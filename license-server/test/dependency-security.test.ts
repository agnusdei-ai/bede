import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("dependency security", () => {
  it("never resolves undici 7.29.0 (GHSA-w293-vg96-wgc3)", () => {
    const lock = JSON.parse(
      readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
    ) as { packages: Record<string, { version?: string }> };
    const versions = Object.entries(lock.packages)
      .filter(([path]) => path.endsWith("node_modules/undici"))
      .map(([, entry]) => entry.version);

    expect(versions.length).toBeGreaterThan(0);
    expect(versions).not.toContain("7.29.0");
  });
});
