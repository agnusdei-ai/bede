import { defineConfig } from 'vitest/config';

// Plain Node environment, not @cloudflare/vitest-pool-workers' Miniflare
// runtime — that package's API broke across minor versions in a way that
// wasn't worth chasing for what these tests actually need. Node 22 has
// native WebCrypto (crypto.subtle, including Ed25519), fetch, Request,
// and Response as globals, which covers everything src/ uses; D1 is
// faked in test/fixtures.ts (FakeD1Database) rather than run against a
// real Miniflare-backed D1 instance. See docs/CHECKOUT_SETUP.md for the
// manual verification steps that cover what these tests don't.
export default defineConfig({
  test: {
    environment: 'node',
  },
});
