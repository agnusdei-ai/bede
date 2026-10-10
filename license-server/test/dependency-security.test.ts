import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("sharp security floor", () => {
  it("locks every sharp copy to the override that fixes libheif and librsvg advisories", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../package.json", import.meta.url), "utf8"),
    );
    const lock = JSON.parse(
      readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
    ) as { packages: Record<string, { version?: string }> };
    const copies = Object.entries(lock.packages).filter(([path]) =>
      path.endsWith("/node_modules/sharp") || path === "node_modules/sharp",
    );

    // GHSA-rgj7-g3m4-5g8c is fixed in 0.35.4; GHSA-wq5f-xc86-pv6w needs 0.35.5.
    expect(manifest.overrides.sharp).toBe("0.35.5");
    expect(copies.length).toBeGreaterThan(0);
    for (const [, dependency] of copies) {
      expect(dependency.version).toBe(manifest.overrides.sharp);
    }
  });
});

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
