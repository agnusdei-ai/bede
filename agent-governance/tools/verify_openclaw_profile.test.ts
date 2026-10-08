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
 * Point GOVERNANCE_DIR at the agent-governance directory before running it.
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
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CORE_TOOL_GROUPS, isKnownCoreToolId } from "./tool-catalog.js";
import { normalizeToolPolicyName } from "./tool-policy-shared.js";
import { buildConfigSchemaCore } from "../config/schema.js";

// No default path: this test runs inside a clone of openclaw/openclaw, so it
// cannot guess where the governance package lives. Point GOVERNANCE_DIR at it.
//
//   GOVERNANCE_DIR=/path/to/agent-governance pnpm vitest run ...
const GOVERNANCE_DIR = process.env.GOVERNANCE_DIR;
if (!GOVERNANCE_DIR && !process.env.GOVERNANCE_PROFILE) {
  throw new Error(
    "set GOVERNANCE_DIR to the agent-governance directory, or GOVERNANCE_PROFILE to the profile file",
  );
}
const PROFILE =
  process.env.GOVERNANCE_PROFILE ?? join(GOVERNANCE_DIR!, "profiles", "openclaw.values.json");
const RUNBOOK = process.env.GOVERNANCE_RUNBOOK ?? PROFILE.replace("values.json", "runbook.md");
const CONFIG = process.env.GOVERNANCE_CONFIG ?? PROFILE.replace("values.json", "hardened.json5");

/** Dotted paths actually SET by the shipped config, read from its structure. */
function configPaths(node: unknown, prefix = "", out = new Set<string>()): Set<string> {
  if (!node || typeof node !== "object" || Array.isArray(node)) return out;
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    out.add(path);
    configPaths(value, path, out);
  }
  return out;
}

/** Minimal JSON5 reader: comments and trailing commas only, which is all this file uses. */
function readJson5(file: string): unknown {
  const stripped = readFileSync(file, "utf8")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "")
    .replace(/,(\s*[}\]])/g, "$1")
    .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:/g, '$1"$2":');
  return JSON.parse(stripped);
}

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

  it("ships a config whose every key exists in this schema", () => {
    // Stronger than scanning prose: this reads the file an operator actually
    // copies. A key that does not exist is accepted silently by a JSON5
    // config and does nothing, so the hardening step reads as done and is not.
    expect(existsSync(CONFIG)).toBe(true);
    const known = schemaPaths((buildConfigSchemaCore() as { schema: unknown }).schema);
    const set = [...configPaths(readJson5(CONFIG))];
    expect(set.length).toBeGreaterThan(10);
    expect(set.filter((key) => !known.has(key))).toEqual([]);
  });

  it("sets the controls the runbook says it sets", () => {
    // Two copies of one fact: the runbook's table and the config file. This
    // is the check that they agree.
    expect(existsSync(RUNBOOK)).toBe(true);
    const set = configPaths(readJson5(CONFIG));
    // Only the runbook's own table of controls — the first backticked key on
    // each table row. Prose elsewhere names keys to explain a default
    // (tools.exec.host) without claiming the config sets them.
    const promised = [
      ...new Set(
        readFileSync(RUNBOOK, "utf8")
          .split("\n")
          .filter((line) => line.startsWith("| `"))
          .map((line) => line.match(/^\| `([A-Za-z][A-Za-z0-9.*]*)`/)?.[1])
          .filter((key): key is string => Boolean(key) && !key!.includes("*")),
      ),
    ].filter((key) => key !== "agents.defaults.skipBootstrap");
    expect(promised.length).toBeGreaterThan(5);
    expect(promised.filter((key) => !set.has(key))).toEqual([]);
  });

  it("the shipped config actually closes the network surface", () => {
    const cfg = readJson5(CONFIG) as any;
    expect(cfg.gateway.bind).toBe("loopback");
    expect(cfg.tools.deny).toContain("gateway");
    expect(cfg.tools.fs.workspaceOnly).toBe(true);
    expect(cfg.agents.defaults.sandbox.mode).not.toBe("off");
  });
});
