import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repository = "agnusdei-ai/bede";
const workflowPath = ".github/workflows/faq-reader.yml";
const requiredJobs = [
  "FAQ copy, PDF and native print cancellation",
  "FAQ export parity (firefox)",
  "FAQ export parity (webkit)",
];

// Public repository: no deployment credential is used or forwarded to GitHub.
async function github(path) {
  const response = await fetch(`https://api.github.com/repos/${repository}/${path}`, {
    headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
    signal: AbortSignal.timeout(15000),
    redirect: "error",
  });
  if (!response.ok) throw new Error(`GitHub evidence lookup failed (HTTP ${response.status}); publication refused.`);
  return response.json();
}

export async function publicationEvidence(sha, {
  get = github, now = Date.now,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  timeoutMs = 12 * 60 * 1000, intervalMs = 60000,
} = {}) {
  assert.match(sha, /^[a-f0-9]{40}$/, "A full checked-out commit SHA is required");
  const deadline = now() + timeoutMs;
  const workflow = await get(`actions/workflows/faq-reader.yml`);
  assert.equal(workflow.path, workflowPath);
  assert.equal(workflow.state, "active", "FAQ workflow is not active");

  while (true) {
    const main = await get("git/ref/heads/main");
    assert.equal(main.object.sha, sha, "Only the current canonical main revision may be published");
    const runs = await get(`actions/workflows/${workflow.id}/runs?branch=main&head_sha=${sha}&per_page=100`);
    const candidates = runs.workflow_runs.filter(run =>
      run.head_sha === sha && run.head_branch === "main"
      && run.head_repository?.full_name === repository
      && run.workflow_id === workflow.id && run.path === workflowPath
      && ["push", "workflow_dispatch"].includes(run.event));
    candidates.sort((a, b) => b.id - a.id);
    const run = candidates[0];
    if (run?.status === "completed") {
      assert.equal(run.conclusion, "success", "Latest canonical FAQ run did not pass");
      assert.ok(Number.isInteger(run.run_attempt) && run.run_attempt > 0);
      const jobs = await get(`actions/runs/${run.id}/attempts/${run.run_attempt}/jobs?per_page=100`);
      assert.ok(jobs.total_count <= 100, "Job list was truncated");
      for (const name of requiredJobs) {
        const matching = jobs.jobs.filter(job => job.name === name);
        assert.equal(matching.length, 1, `Expected one completed job: ${name}`);
        const job = matching[0];
        assert.equal(job.head_sha, sha, `Wrong revision: ${name}`);
        assert.equal(job.status, "completed", `Incomplete job: ${name}`);
        assert.equal(job.conclusion, "success", `Unsuccessful job: ${name}`);
        assert.ok(job.steps?.some(step => step.name.startsWith("Retain ")
          && step.status === "completed" && step.conclusion === "success"),
        `Evidence upload did not succeed: ${name}`);
      }
      const listing = await get(`actions/runs/${run.id}/artifacts?per_page=100`);
      assert.ok(listing.total_count <= 100, "Artifact list was truncated");
      const expected = ["", "firefox-", "webkit-"].map(engine =>
        `faq-reader-${engine}${run.id}-${run.run_attempt}`);
      const artifacts = expected.map(name => {
        const matching = listing.artifacts.filter(artifact => artifact.name === name);
        assert.equal(matching.length, 1, `Missing or ambiguous evidence: ${name}`);
        const artifact = matching[0];
        assert.equal(artifact.expired, false, `Expired evidence: ${name}`);
        assert.ok(artifact.size_in_bytes > 0, `Empty evidence: ${name}`);
        assert.ok(Date.parse(artifact.expires_at) > now(), `Evidence has expired: ${name}`);
        assert.equal(artifact.workflow_run?.id, run.id, `Wrong evidence run: ${name}`);
        assert.equal(artifact.workflow_run?.head_sha, sha, `Wrong evidence revision: ${name}`);
        return { id: artifact.id, name, expiresAt: artifact.expires_at };
      });
      // Recheck after evidence lookup so a moving main does not silently pass.
      assert.equal((await get("git/ref/heads/main")).object.sha, sha, "Main changed while checking evidence");
      return { repository, sha, runId: run.id, attempt: run.run_attempt,
        runUrl: run.html_url, jobs: requiredJobs, artifacts };
    }
    if (now() + intervalMs > deadline) {
      throw new Error("No successful canonical FAQ run before the deadline; publication refused. Run the FAQ workflow on this main SHA, then retry the build.");
    }
    console.log("Waiting for FAQ Actions evidence for the checked-out main revision...");
    await sleep(intervalMs);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  try {
    const sha = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
    const evidence = await publicationEvidence(sha);
    const directory = resolve(root, "generated-artifacts/faq-publication");
    mkdirSync(directory, { recursive: true });
    writeFileSync(resolve(directory, "approved-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
    console.log(`FAQ publication gate passed: ${sha}, run ${evidence.runId}, attempt ${evidence.attempt}`);
  } catch (error) {
    console.error(`FAQ publication gate blocked the build: ${error.message}`);
    process.exitCode = 1;
  }
}
