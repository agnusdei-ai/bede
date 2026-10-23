import { afterEach, beforeEach, expect, vi } from "vitest";

// Unit tests must inject email/billing fakes, never contact external services.
const blockedFetch = vi.fn(async () => {
  throw new Error("External fetch blocked: inject a test transport");
});

beforeEach(() => {
  blockedFetch.mockClear();
  vi.stubGlobal("fetch", blockedFetch);
});

afterEach(() => {
  try {
    // Also detect requests whose errors were caught by application handlers.
    expect(blockedFetch, "Unit test attempted an external request").not.toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
  }
});
