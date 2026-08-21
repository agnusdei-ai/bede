// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Agnus Dei Technologies, LLC
/**
 * Verifies profiles/openclaw.values.json against OpenClaw's real tool registry.
 *
 * RUN BY HAND, INSIDE A CLONE OF openclaw/openclaw — it imports that project's
 * modules, so it cannot run in this repository's CI and is deliberately not
 * wired into one. Same posture as the by-hand e2e checks in scripts/.
 *
 *   git clone --depth 1 https://github.com/openclaw/openclaw
 *   cd openclaw && pnpm install --frozen-lockfile --ignore-scripts
 *   cp <this file> src/agents/governance-profile-tool-names.test.ts
 *   pnpm vitest run src/agents/governance-profile-tool-names.test.ts \
 *     --config test/vitest/vitest.agents-core.config.ts
 *
 * Point GOVERNANCE_PROFILE at the profile if it is not at the default path.
 *
 * Last run: 2026-08-21 against commit 07c8b42a71b0856f3a822ca641322a1aa0a49f3c,
 * 4 passed. That run is what caught `cron` being an alias whose canonical id
 * is `automations` — a fact the published docs table does not state.
 *
 * Not an OpenClaw test — a check that an external governance prompt naming
 * OpenClaw's tools names ones that actually exist. It asks the registry's own
 * predicates (isKnownCoreToolId, normalizeToolPolicyName, CORE_TOOL_GROUPS)
 * rather than comparing against a copied list, so it cannot pass on a stale
 * copy of the truth.
 *
 */
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { CORE_TOOL_GROUPS, isKnownCoreToolId } from "./tool-catalog.js";
import { normalizeToolPolicyName } from "./tool-policy-shared.js";
import { buildConfigSchemaCore } from "../config/schema.js";

const PROFILE =
  process.env.GOVERNANCE_PROFILE ??
  "/home/user/bede/agent-governance/profiles/openclaw.values.json";
const RUNBOOK = process.env.GOVERNANCE_RUNBOOK ?? PROFILE.replace("values.json", "runbook.md");

/** Every config path the schema actually defines. */
function schemaPaths(node: unknown, prefix = "", out = new Set<string>()): Set<string> {
  if (!node || typeof node !== "object") return out;
  const n = node as Record<string, any>;
  const props = n.properties ?? n.fields ?? n.children;
  if (props && typeof props === "object") {
    for (const [key, value] of Object.entries<any>(props)) {
      const path = prefix ? `${prefix}.${key}` : key;
      out.add(path);
      schemaPaths(value, path, out);
      if (value?.additionalProperties) schemaPaths(value.additionalProperties, `${path}.*`, out);
      if (value?.items) schemaPaths(value.items, path, out);
    }
  }
  return out;
}

/** Identifiers the profile marks with backticks, minus non-tool notation. */
function citedIdentifiers(): string[] {
  const raw = JSON.parse(readFileSync(PROFILE, "utf8")) as Record<string, string>;
  const prose = Object.entries(raw)
    .filter(([key]) => !key.startsWith("_"))
    .map(([, value]) => value)
    .join("\n");
  const cited = [...prose.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  return [...new Set(cited)].filter(
    (id) =>
      !id.includes(".") && // config keys: tools.fs.workspaceOnly
      !id.includes("*") && // wildcards: conversations_*
      !id.includes(" "),
  );
}

describe("agent-governance OpenClaw profile", () => {
  it("has a profile to check", () => {
    expect(existsSync(PROFILE)).toBe(true);
    expect(citedIdentifiers().length).toBeGreaterThan(10);
  });

  it("names only tools or groups this registry actually knows", () => {
    const unknown = citedIdentifiers().filter((id) => {
      if (id.startsWith("group:")) return !(id in CORE_TOOL_GROUPS);
      if (id === "bundle-mcp") return false; // plugin id, not a core tool
      return !isKnownCoreToolId(normalizeToolPolicyName(id));
    });
    expect(unknown).toEqual([]);
  });

  it("resolves bash to exec, as the profile claims", () => {
    expect(normalizeToolPolicyName("bash")).toBe("exec");
    expect(isKnownCoreToolId("exec")).toBe(true);
  });

  it("names every tool that can act outside the process", () => {
    // If the registry gains one of these and the profile has no rule for it,
    // the governance prompt has a hole exactly where it matters most.
    const highRisk = ["exec", "write", "edit", "apply_patch", "message", "web_fetch", "gateway", "automations", "sessions_spawn", "skill_workshop"];
    const cited = new Set(citedIdentifiers().map((id) => normalizeToolPolicyName(id)));
    expect(highRisk.filter((id) => !cited.has(id))).toEqual([]);
  });

  it("cites only config keys this schema actually defines", () => {
    // The runbook tells an operator to set these. A key that does not exist is
    // accepted silently by a JSON5 config and simply does nothing, so the
    // hardening step reads as done and is not.
    // Never skip on a missing runbook: a silent pass for a check that never
    // ran is the failure mode this whole file exists to avoid.
    expect(existsSync(RUNBOOK)).toBe(true);
    const known = schemaPaths((buildConfigSchemaCore() as { schema: unknown }).schema);
    expect(known.size).toBeGreaterThan(500);
    const cited = [
      ...new Set(
        [
          ...readFileSync(RUNBOOK, "utf8").matchAll(/\b(?:gateway|tools|agents)\.[A-Za-z][A-Za-z0-9.*]*/g),
        ].map((m) => m[0].replace(/\.$/, "")),
      ),
    ];
    expect(cited.length).toBeGreaterThan(3);
    expect(cited.filter((key) => !known.has(key))).toEqual([]);
  });
});
