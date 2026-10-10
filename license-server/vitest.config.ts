import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

/**
 * Two runtimes, on purpose:
 *
 *  - node: everything except the workerd signing proof. The D1 fake runs
 *    real SQLite (better-sqlite3) so unique constraints, on-conflict
 *    clauses, and max() have real semantics — not emulated ones.
 *  - workerd: the Ed25519 proof (test/runtime-signing.test.ts) MUST run in
 *    the actual Workers runtime — a Node WebCrypto pass proves nothing
 *    about what Cloudflare's runtime accepts (spec D1). `cloudflareTest()`
 *    is the vitest-4 wiring: a Vite plugin that installs the pool.
 */
export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "node",
          environment: "node",
          include: ["test/**/*.test.ts"],
          exclude: ["test/runtime-signing.test.ts"],
        },
      },
      {
        plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.jsonc" } })],
        test: {
          name: "workerd",
          include: ["test/runtime-signing.test.ts"],
        },
      },
    ],
  },
});
