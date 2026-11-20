import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { publicationEvidence, isBranchBuild, SUPERSEDED } from "./publication-gate.mjs";

const sha = "a".repeat(40);
const names = ["FAQ copy, PDF and native print cancellation", "FAQ export parity (firefox)", "FAQ export parity (webkit)"];
function fixture() {
  const workflow = { id: 10, state: "active", path: ".github/workflows/faq-reader.yml" };
  const run = { id: 123, run_attempt: 2, workflow_id: 10, path: workflow.path,
    head_sha: sha, head_branch: "main", head_repository: { full_name: "agnusdei-ai/bede" },
    event: "push", status: "completed", conclusion: "success", html_url: "https://github.com/agnusdei-ai/bede/actions/runs/123" };
  const jobs = { total_count: 3, jobs: names.map(name => ({
    name, head_sha: sha, status: "completed", conclusion: "success",
    steps: [{ name: "Retain FAQ evidence even on failure", status: "completed", conclusion: "success" }],
  })) };
  const artifacts = { total_count: 3, artifacts: ["", "firefox-", "webkit-"].map((engine, id) => ({
    id, name: `faq-reader-${engine}123-2`, expired: false, size_in_bytes: 200,
    expires_at: "2030-01-01T00:00:00Z", workflow_run: { id: 123, head_sha: sha },
  })) };
  let time = 0;
  const state = { workflow, run, jobs, artifacts, main: sha, runs: [run] };
  const calls = [];
  return Object.assign(state, { options: {
    now: () => time, sleep: async ms => { time += ms; },
    timeoutMs: 2000, intervalMs: 1000,
    get: async path => {
      calls.push(path);
      if (path === "actions/workflows/faq-reader.yml") return state.workflow;
      if (path === "git/ref/heads/main") return { object: { sha: state.main } };
      if (path.includes("/runs?")) return { workflow_runs: state.runs };
      if (path.includes("/jobs?")) return state.jobs;
      if (path.includes("/artifacts?")) return state.artifacts;
      throw new Error(`Unexpected endpoint: ${path}`);
    },
  }, calls });
}

test("publication requires all three successful jobs and current-attempt evidence for the exact main SHA", async () => {
  const f = fixture();
  const result = await publicationEvidence(sha, f.options);
  assert.equal(result.runId, 123);
  assert.equal(result.attempt, 2);
  assert.equal(result.artifacts.length, 3);
  assert.ok(f.calls.includes("actions/runs/123/attempts/2/jobs?per_page=100"));
});

test("wrong branch, SHA, repository, event or workflow cannot authorize publication", async () => {
  for (const change of [
    { head_branch: "feature" }, { head_sha: "b".repeat(40) }, { event: "pull_request" },
    { event: "merge_group" }, { workflow_id: 999 }, { path: ".github/workflows/other.yml" },
    { head_repository: { full_name: "someone/bede" } },
  ]) {
    const f = fixture();
    Object.assign(f.run, change);
    await assert.rejects(publicationEvidence(sha, f.options), /deadline/);
  }
  const f = fixture();
  f.main = "b".repeat(40);
  await assert.rejects(publicationEvidence(sha, f.options), /current canonical main/);
});

test("missing, pending or failed runs block; older green runs cannot override a newer failure", async () => {
  for (const mode of ["missing", "queued", "failure", "cancelled", "skipped", "newer-failure"]) {
    const f = fixture();
    if (mode === "missing") f.runs = [];
    else if (mode === "queued") f.run.status = "queued";
    else if (mode === "newer-failure") f.runs.push({ ...f.run, id: 124, conclusion: "failure" });
    else f.run.conclusion = mode;
    await assert.rejects(publicationEvidence(sha, f.options));
  }
});

test("skipped jobs, failed uploads, missing jobs and truncated results block", async () => {
  for (const change of [
    f => { f.jobs.jobs[0].conclusion = "skipped"; },
    f => { f.jobs.jobs[0].steps[0].conclusion = "failure"; },
    f => { f.jobs.jobs[0].head_sha = "b".repeat(40); },
    f => { f.jobs.jobs.pop(); },
    f => { f.jobs.total_count = 101; },
    f => { f.artifacts.total_count = 101; },
  ]) {
    const f = fixture();
    change(f);
    await assert.rejects(publicationEvidence(sha, f.options));
  }
});

test("missing, empty, expired, wrong-run and stale-attempt evidence block", async () => {
  for (const change of [
    f => { f.artifacts.artifacts.pop(); },
    f => { f.artifacts.artifacts[0].size_in_bytes = 0; },
    f => { f.artifacts.artifacts[0].expired = true; },
    f => { f.artifacts.artifacts[0].expires_at = "invalid"; },
    f => { f.artifacts.artifacts[0].expires_at = "1960-01-01"; },
    f => { f.artifacts.artifacts[0].workflow_run.head_sha = "b".repeat(40); },
    f => { f.artifacts.artifacts[0].workflow_run.id = 122; },
    f => { f.artifacts.artifacts[0].name = "faq-reader-123-1"; },
  ]) {
    const f = fixture();
    change(f);
    await assert.rejects(publicationEvidence(sha, f.options));
  }
});

test("API failures and disabled workflow fail closed", async () => {
  const f = fixture();
  f.workflow.state = "disabled_manually";
  await assert.rejects(publicationEvidence(sha, f.options));
  f.options.get = async () => { throw new Error("API unavailable"); };
  await assert.rejects(publicationEvidence(sha, f.options), /API unavailable/);
});

test("main moving during evidence lookup blocks publication", async () => {
  const f = fixture();
  const get = f.options.get;
  f.options.get = async path => {
    const value = await get(path);
    if (path.includes("/artifacts?")) f.main = "b".repeat(40);
    return value;
  };
  await assert.rejects(publicationEvidence(sha, f.options), /Main changed/);
});

test("existing build runs the guard before dependencies, output removal and assembly, without a bypass", () => {
  const source = readFileSync(new URL("../build_pages_site.sh", import.meta.url), "utf8");
  const guard = source.indexOf("node scripts/faq-browser/publication-gate.mjs");
  assert.ok(guard > 0);
  for (const step of ["npm ci", "rm -rf publish", "cp -r site/* publish/"]) {
    assert.ok(guard < source.indexOf(step));
  }
  assert.match(source, /set -euo pipefail/);
  assert.doesNotMatch(source.slice(guard, source.indexOf("echo \"Building demo")), /\|\| true|SKIP|BYPASS/);
});

test("Wrangler itself invokes the guard without changing the Worker or static assets", () => {
  const source = readFileSync(new URL("../../wrangler.jsonc", import.meta.url), "utf8");
  const config = JSON.parse(source.replace(/^\s*\/\/.*$/gm, ""));
  assert.deepEqual(config, {
    name: "bede", compatibility_date: "2026-07-01",
    build: { command: "node scripts/faq-browser/publication-gate.mjs" },
    assets: { directory: "./publish" },
  });
});

test("a superseded main commit is refused with its own message, never published", async () => {
  const f = fixture();
  f.main = "b".repeat(40);
  await assert.rejects(publicationEvidence(sha, f.options), /superseded by a newer main commit/);
  assert.match(SUPERSEDED, /Nothing from this build is published/);
});

test("only a named branch other than main is a branch build; absent, blank and main run the full gate", () => {
  assert.equal(isBranchBuild({ WORKERS_CI_BRANCH: "claude/some-feature" }), true);
  assert.equal(isBranchBuild({ WORKERS_CI_BRANCH: " feature " }), true);
  for (const value of [undefined, "", "   ", "main", " main "]) {
    assert.equal(isBranchBuild({ WORKERS_CI_BRANCH: value }), false, JSON.stringify(value));
  }
  assert.equal(isBranchBuild({}), false);
});

test("the real command skips a branch build with exit 0 and runs the full gate otherwise", () => {
  const script = new URL("./publication-gate.mjs", import.meta.url).pathname;
  const run = branch => spawnSync(process.execPath, [script], {
    encoding: "utf8", timeout: 15000,
    env: { ...process.env, ...(branch === undefined ? {} : { WORKERS_CI_BRANCH: branch }) },
  });
  const skipped = run("claude/some-feature");
  assert.equal(skipped.status, 0);
  assert.match(skipped.stdout, /branch build; nothing is published from a branch/);
  // main, blank and unset must NOT take the skip path (they reach the real
  // gate, which may fail or still be waiting when the timeout kills it).
  for (const branch of ["main", "", undefined]) {
    const result = run(branch);
    assert.doesNotMatch(result.stdout ?? "", /branch build; nothing is published/, String(branch));
    // The real gate ran: it passed, was blocked, or was still waiting for
    // evidence when the timeout stopped it. Which one depends on the network and
    // on whether this checkout is main's head, so only the fact it ran is asserted.
    assert.match(`${result.stdout}${result.stderr}`, /FAQ publication gate (passed|blocked)|Waiting for FAQ Actions evidence/, String(branch));
  }
});

test("both build entry points still invoke the gate unconditionally; the skip lives inside it", () => {
  const script = readFileSync(new URL("../build_pages_site.sh", import.meta.url), "utf8");
  assert.doesNotMatch(script, /WORKERS_CI_BRANCH/);
  assert.doesNotMatch(readFileSync(new URL("../../wrangler.jsonc", import.meta.url), "utf8"), /WORKERS_CI_BRANCH/);
});
