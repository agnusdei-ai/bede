#!/usr/bin/env node
/**
 * Synthetic end-to-end check of the public demo — the detector half of the
 * watchdog loop (see .github/workflows/demo-watchdog.yml).
 *
 * WHY A REAL BROWSER, AND WHY THE REAL JOURNEY
 *
 * `keep-demo-warm.yml` already curls /health every 10 minutes, and on
 * 2026-08-04 it reported healthy throughout an outage that made the demo
 * completely unusable. It could not have caught it: curl is not a browser,
 * so it does not evaluate Content-Security-Policy, does not send an Origin
 * header, and does not enforce CORS. The failure lived entirely in those
 * layers. Everything a component check can see was fine.
 *
 * So this drives an actual Chromium instance through the actual first
 * thing a visitor does — load /bede/, click "Generate my code" — and
 * reports what a visitor would experience. It is the only check in this
 * repo that can fail for the reason a user would.
 *
 * WHAT MAKES IT MACHINE-ACTIONABLE
 *
 * It reads back the always-on diagnostics buffer (demo/src/diagnostics.ts)
 * via __bedeDebugEntries() and includes it in the report. That buffer is
 * what turns "it didn't work" into "connect-src blocked this exact URI",
 * which is the difference between a human having to investigate and an
 * agent being able to act. This script is the reason those diagnostics are
 * worth collecting at all in an unattended setting.
 *
 * OUTPUT is JSON on stdout — one object, always, pass or fail — so the
 * workflow can hand it to an agent verbatim without scraping logs.
 *
 * PRIVACY: this is a synthetic session. The "student" is a fixed fake name
 * on a throwaway demo code, and nothing about a real family is read,
 * transmitted, or stored. The diagnostics it captures are its own.
 *
 * Usage:  node scripts/synthetic_journey.mjs https://agnusdei.ai/bede/
 */
import { chromium } from 'playwright';

const TARGET = process.argv[2] || process.env.DEMO_URL || 'https://agnusdei.ai/bede/';
const TIMEOUT_MS = Number(process.env.JOURNEY_TIMEOUT_MS || 90_000);

/** Everything the run observed. Emitted whole, pass or fail. */
const report = {
  target: TARGET,
  startedAt: new Date().toISOString(),
  ok: false,
  failedStep: null,
  summary: '',
  cspViolations: [],
  consoleErrors: [],
  networkFailures: [],
  requests: [],
  diagnosticsBuffer: [],
};

function finish(code) {
  report.finishedAt = new Date().toISOString();
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  process.exit(code);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage();

// A CSP block is the one failure with no server-side trace at all, so it is
// captured first-class rather than inferred from a generic console error.
page.on('console', (m) => {
  if (m.type() !== 'error' && m.type() !== 'warning') return;
  const text = m.text();
  if (/Content Security Policy|Refused to connect/i.test(text)) {
    report.cspViolations.push(text);
  } else if (m.type() === 'error') {
    report.consoleErrors.push(text);
  }
});
page.on('requestfailed', (r) => {
  report.networkFailures.push({
    url: new URL(r.url()).origin + new URL(r.url()).pathname, // no query string — see privacy note
    method: r.method(),
    failure: r.failure()?.errorText ?? 'unknown',
  });
});
page.on('response', (r) => {
  const u = new URL(r.url());
  // Only the app's own API calls; page assets are noise here.
  if (/\/auth\/|\/tutor\/|\/feedback|\/health/.test(u.pathname)) {
    report.requests.push({ url: u.origin + u.pathname, status: r.status() });
  }
});

try {
  // ── Step 1: the page loads at all ────────────────────────────────────
  const res = await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
  if (!res || !res.ok()) {
    report.failedStep = 'load';
    report.summary = `The demo page did not load (HTTP ${res ? res.status() : 'no response'}).`;
    finish(1);
  }

  // ── Step 1b: the consent gate ────────────────────────────────────────
  // The demo shows ConsentModal before anything else (see
  // demo/src/useConsent.ts), and it is a full-screen overlay that
  // intercepts pointer events — so the button below is visible and
  // clickable-looking but not actually reachable. Found by running this
  // check rather than reasoning about it: the first version went straight
  // for the button and timed out against an overlay it never mentioned.
  //
  // Dismissed by clicking it rather than by pre-seeding localStorage,
  // deliberately: consent is part of the real journey, and a check that
  // skips it would stop noticing if that screen ever broke.
  const consent = page.getByRole('button', { name: /I understand and agree/i }).first();
  if (await consent.isVisible().catch(() => false)) {
    await consent.click();
    await consent.waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => {});
  }

  // ── Step 2: the visitor's first and only action ──────────────────────
  // Matched by role/text rather than a CSS class so a styling change does
  // not produce a false alarm — this check must fail for real reasons only,
  // or it will be ignored, which is worse than not having it.
  const button = page.getByRole('button', { name: /generate my code/i }).first();
  await button.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {
    report.failedStep = 'find-button';
    report.summary = 'The "Generate my code" button never appeared — the app may not have mounted.';
  });
  if (report.failedStep) finish(1);

  await button.click();

  // ── Step 3: did a session actually start? ────────────────────────────
  // Success = the app leaves the entry screen. Failure = the inline error
  // the demo shows, which is deliberately vague to a visitor and therefore
  // useless on its own — the diagnostics below are what explain it.
  const outcome = await Promise.race([
    page
      .getByText(/could not reach the server|could not start a session|not enabled|too many/i)
      .first()
      .waitFor({ state: 'visible', timeout: TIMEOUT_MS })
      .then(() => 'error'),
    page
      .getByRole('button', { name: /generate my code/i })
      .first()
      .waitFor({ state: 'hidden', timeout: TIMEOUT_MS })
      .then(() => 'started'),
  ]).catch(() => 'timeout');

  // Read the app's own always-on diagnostics — the whole point of this
  // check being a browser rather than a curl.
  report.diagnosticsBuffer = await page
    .evaluate(() => (window.__bedeDebugEntries ? window.__bedeDebugEntries() : []))
    .catch(() => []);

  if (outcome === 'started') {
    report.ok = true;
    report.summary = 'A demo session started successfully.';
    finish(0);
  }

  report.failedStep = outcome === 'timeout' ? 'timeout' : 'generate-code';
  const visible = await page
    .getByText(/could not reach the server|could not start a session|not enabled|too many/i)
    .first()
    .textContent()
    .catch(() => null);

  // Name the cause ONLY when the evidence actually supports it, and say
  // "unknown" otherwise.
  //
  // The first version of this block read "if there are any CSP violations,
  // blame CSP for the backend" — and on its first real run it did exactly
  // that against an unrelated media-src violation on a data: URI, while the
  // true cause (no VITE_DEMO_API_BASE configured) sat in the diagnostics
  // buffer being ignored. A confident wrong answer is worse than no answer
  // anywhere, and considerably worse here: this report is the input to an
  // unattended repair agent, so a misattribution does not merely mislead a
  // human who can push back, it directs an automated change at the wrong
  // file. Attribution is therefore narrow by construction — connect-src
  // specifically, and only when the blocked URI is the thing the app was
  // actually trying to reach.
  const backendBlockedByCsp = report.cspViolations.some(
    (v) => /connect-src/i.test(v) && /\/auth\/|\/tutor\/|onrender\.com/i.test(v)
  );
  // The app's own account of what went wrong, recorded by
  // demo/src/diagnostics.ts before friendlyErrorMessage replaced it with
  // vaguer wording. Preferred over inference wherever it exists.
  const appReported = report.diagnosticsBuffer
    .map((e) => e.message)
    .find((m) => m.startsWith('error→friendly'));

  if (backendBlockedByCsp) {
    report.summary =
      'A Content-Security-Policy blocked the demo from reaching its backend. ' +
      'The request was never sent, so the server logs will show nothing. ' +
      'This is a deployment header problem (site/_headers), not a backend outage.';
  } else if (appReported && /not configured/i.test(appReported)) {
    report.summary =
      'The demo build has no backend URL compiled into it — VITE_DEMO_API_BASE ' +
      'was unset at build time. This is a build/deploy configuration problem, ' +
      'not a runtime failure. (Expected when running the check against a local ' +
      'build; a real deployment sets it.)';
  } else if (report.networkFailures.length) {
    report.summary =
      `The demo could not complete a request: ${report.networkFailures[0].failure}. ` +
      'Check CORS_ORIGINS on the API and that the backend is reachable.';
  } else if (report.requests.some((r) => r.status >= 500)) {
    report.summary = 'The backend returned a server error to the demo.';
  } else {
    // No confident attribution. Report what was seen and say so plainly —
    // the repair agent's prompt requires it to investigate rather than act
    // when the cause is unstated, which only works if this is honest about
    // not knowing.
    report.summary =
      (visible
        ? `The demo showed an error to the visitor: "${visible.trim()}". `
        : 'The demo did not start a session and gave no visible reason. ') +
      'Cause not determined from the browser side — see diagnosticsBuffer, ' +
      'requests and cspViolations below, and check the API logs.';
  }
  if (report.cspViolations.length && !backendBlockedByCsp) {
    // Kept visible but explicitly not blamed, so it is neither hidden nor
    // mistaken for the cause.
    report.summary +=
      ` (Note: ${report.cspViolations.length} unrelated CSP violation(s) were ` +
      'also recorded — not blocking the backend call.)';
  }
  finish(1);
} catch (err) {
  report.failedStep = report.failedStep || 'exception';
  report.summary = `The check itself failed: ${err?.name}: ${err?.message}`;
  finish(1);
} finally {
  await browser.close().catch(() => {});
}
