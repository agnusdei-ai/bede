// Minimal reproduction for the macOS WebKit reload crash (release-repair cycle
// webkit-1). Independent of Bede: a tiny local page, no app, no API.
//
// Hypothesis from the instrumented journeys: WebKit's Navigation API does not
// record history.pushState, so navigation.currentEntry stays on the first URL;
// a reload then leaves currentEntry null; and a SECOND reload asserts in
// WebCore::Navigation::initializeForNewWindow. Each variant changes ONE factor
// against B. It prints one REPRO line per run and never exits non-zero for a
// crash: a crash is the observation, not a failure of this script.
//
// Evidence, when asked for (the diagnosis workflow's minimal job sets both):
// RESULTS_FILE gets every run, the tallies and the environment as JSON, and
// TRACE_DIR gets one Playwright trace per run. A run that needs an API the
// engine lacks (variant I without the Navigation API) is NOT RUN, never a
// pass: it is counted apart from the runs that executed.
const http = require('http');
const fs = require('fs');
const path = require('path');
const pw = require('playwright');

const PAGE = '<!doctype html><meta charset="utf-8"><title>repro</title><p id="p">page</p>';
const VARIANTS = {
  A_no_push_two_reloads: { push: null, reloads: 2 },
  B_push_two_reloads: { push: 'push', reloads: 2 },
  C_push_one_reload: { push: 'push', reloads: 1 },
  D_replace_two_reloads: { push: 'replace', reloads: 2 },
  E_real_navigation_two_reloads: { push: 'assign', reloads: 2 },
  F_push_three_reloads: { push: 'push', reloads: 3 },
  // Candidate workarounds Bede could ship, each against B:
  G_push_reload_relocate_reload: { push: 'push', reloads: 2, relocateAfterFirst: true },
  H_push_relocate_two_reloads: { push: 'push', relocate: true, reloads: 2 },
  I_push_navigation_api_reloads: { push: 'push', reloads: 2, navReload: true },
};
const REPEATS = Number(process.env.REPEATS || 3);
const RESULTS_FILE = process.env.RESULTS_FILE || '';
const TRACE_DIR = process.env.TRACE_DIR || '';
const ENGINES = (process.env.ENGINES || 'webkit,chromium,firefox').split(',');

async function navState(pg) {
  return pg.evaluate(() => ({
    path: location.pathname,
    nav: 'navigation' in window ? { entries: navigation.entries().length, index: navigation.currentEntry?.index ?? null,
      url: navigation.currentEntry?.url ? new URL(navigation.currentEntry.url).pathname : null } : null,
  })).catch(e => ({ error: String(e.message || e).slice(0, 80) }));
}

async function run(br, engine, name, v, rep, base) {
  const ctx = await br.newContext();
  if (TRACE_DIR) await ctx.tracing.start({ snapshots: true }).catch(() => {});
  const pg = await ctx.newPage();
  let crashed = false; pg.on('crash', () => { crashed = true; });
  const trail = [];
  let outcome = 'ok';
  try {
    await pg.goto(base + '/');
    if (v.navReload && !(await pg.evaluate(() => 'navigation' in window))) outcome = 'not_run: no Navigation API';
    if (outcome.startsWith('not_run')) throw null;
    if (v.push === 'push') await pg.evaluate(() => history.pushState({}, '', '/session'));
    if (v.push === 'replace') await pg.evaluate(() => history.replaceState({}, '', '/session'));
    if (v.push === 'assign') { await pg.goto(base + '/session'); }
    // A real navigation to the page's own URL, which is what the app could do
    // to make WebKit rebuild an honest Navigation API record.
    const relocate = async () => { await Promise.all([pg.waitForNavigation({ timeout: 20000 }), pg.evaluate(() => location.replace(location.href))]); };
    if (v.relocate) await relocate();
    for (let k = 0; k < v.reloads; k++) {
      trail.push(await navState(pg));
      if (v.navReload) await Promise.all([pg.waitForNavigation({ timeout: 20000 }), pg.evaluate(() => navigation.reload())]);
      else await pg.reload({ timeout: 20000 });
      if (v.relocateAfterFirst && k === 0) { trail.push(await navState(pg)); await relocate(); }
    }
    trail.push(await navState(pg));
  } catch (e) {
    if (!outcome.startsWith('not_run')) outcome = crashed || /crash/i.test(String(e)) ? 'crashed' : `error: ${String(e).split('\n')[0].slice(0, 100)}`;
  }
  if (crashed) outcome = 'crashed';
  console.log(`REPRO engine=${engine} variant=${name} run=${rep + 1} outcome=${outcome} trail=${JSON.stringify(trail)}`);
  if (TRACE_DIR) {
    // A crashed page can leave nothing to stop; the run's outcome stands either way.
    await ctx.tracing.stop({ path: path.join(TRACE_DIR, `${engine}-${name}-run${rep + 1}.zip`) }).catch(() => {});
  }
  await ctx.close().catch(() => {});
  return { outcome, trail };
}

function environment() {
  // The tested environment, recorded rather than implied: a Playwright WebKit
  // build is not a Safari release, so its exact build revision is named.
  const os = require('os');
  let pwVersion = 'unknown', builds = {};
  try { pwVersion = require('playwright/package.json').version; } catch {}
  try {
    // browsers.json is not an exported subpath, so read it from disk beside
    // playwright-core's own package.json.
    const path = require('path'), fs = require('fs');
    const from = path.dirname(require.resolve('playwright/package.json'));
    const core = path.dirname(require.resolve('playwright-core/package.json', { paths: [from] }));
    for (const b of JSON.parse(fs.readFileSync(path.join(core, 'browsers.json'), 'utf8')).browsers) builds[b.name] = { revision: b.revision, version: b.browserVersion || null };
  } catch (e) { builds = { error: String(e.message || e).slice(0, 80) }; }
  return { playwright: pwVersion, builds, os: `${os.type()} ${os.release()} ${os.arch()}`, node: process.version };
}

(async () => {
  console.log(`ENV ${JSON.stringify(environment())}`);
  const versions = {};
  const server = http.createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(PAGE); });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const tally = {};
  const runs = [];
  const env = environment();
  if (TRACE_DIR) fs.mkdirSync(TRACE_DIR, { recursive: true });
  for (const engine of ENGINES) {
    let br;
    try { br = await pw[engine].launch(); } catch (e) { console.log(`REPRO engine=${engine} not_run: ${String(e).split('\n')[0].slice(0, 120)}`); continue; }
    console.log(`REPRO engine=${engine} version=${br.version()}`);
    versions[engine] = br.version();
    for (const [name, v] of Object.entries(VARIANTS)) {
      for (let rep = 0; rep < REPEATS; rep++) {
        const { outcome: o, trail } = await run(br, engine, name, v, rep, base);
        runs.push({ engine, variant: name, run: rep + 1, outcome: o, trail });
        const key = `${engine}/${name}`; tally[key] = tally[key] || { crashed: 0, runs: 0, not_run: 0 };
        if (o.startsWith('not_run')) { tally[key].not_run++; continue; }
        tally[key].runs++; if (o === 'crashed') tally[key].crashed++;
      }
    }
    await br.close();
  }
  for (const [k, t] of Object.entries(tally)) {
    console.log(`TALLY ${k} ${t.runs ? `crashed ${t.crashed}/${t.runs}` : 'NOT_RUN'}${t.not_run ? ` not_run ${t.not_run}` : ''}`);
  }
  if (RESULTS_FILE) fs.writeFileSync(RESULTS_FILE, JSON.stringify({ env, versions, repeats: REPEATS, tally, runs }, null, 2));
  server.close();
})();
