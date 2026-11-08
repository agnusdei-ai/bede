// Cross-platform browser journeys (#599/#755). Synthetic data only.
// Started by run_journeys.py. Every browser in F.browsers runs at once
// against ONE service: per browser, one parent device and one child device.
// Browsers are the real installed ones on the runner: Google Chrome
// (channel "chrome"), Microsoft Edge (channel "msedge"), and on macOS
// Playwright's WebKit build (the Safari engine, NOT Safari itself).
const pw = require('playwright');
const fs = require('fs');
const path = require('path');
const F = JSON.parse(fs.readFileSync(process.env.FIX));
const OUT = F.out, CTL = F.ctl, T0 = Date.now(), now = () => Date.now();
const steps = [], checks = [];
const N = F.browsers.length, LEARNERS = Object.keys(F.learners);

function check(user, name, ok, note = '') { checks.push({ user, check: name, ok: !!ok, note: String(note).slice(0, 300) }); console.log(`${ok ? 'PASS' : 'FAIL'} ${user} ${name} ${String(note).slice(0, 200)}`); }
async function step(user, name, fn) {
  const t0 = now(); let ok = true, note = '', v;
  try { v = await fn(); } catch (e) { ok = false; note = String(e).split('\n')[0].slice(0, 240); }
  steps.push({ user, step: name, t0: t0 - T0, ms: now() - t0, ok, note });
  console.log(`${ok ? 'ok  ' : 'ERR '} ${user} ${name} ${now() - t0}ms ${note}`);
  if (!ok) throw new Error(`${user}/${name}: ${note}`);
  return v;
}
const B = {};
const SIZE = { start: 2 * N, overlap: 2 * N, save: N, answer_done: N, reopen: 2 * N };
function get(n) { if (!B[n]) { let r; const p = new Promise(x => r = x); B[n] = { c: 0, p, r }; } return B[n]; }
function barrier(n) { const b = get(n); b.c++; if (b.c >= SIZE[n]) b.r(); return b.p; }
const waitFor = n => get(n).p;
function release(names) { for (const n of names) if (get(n).c < SIZE[n]) barrier(n); }
const waitFile = async (f, ms = 180000) => { for (let i = 0; i < ms / 200; i++) { if (fs.existsSync(path.join(CTL, f))) return; await new Promise(r => setTimeout(r, 200)); } throw new Error('timed out waiting for ' + f); };

const apiCall = (pg, p, method = 'GET', body) => pg.evaluate(async ([p, method, body]) => {
  let tok = null; for (const k of Object.keys(sessionStorage)) { try { const v = JSON.parse(sessionStorage.getItem(k)); if (v?.state?.token) tok = v.state.token } catch {} }
  const r = await fetch('/api' + p, { method, headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.text() };
}, [p, method, body]);
const replies = c => c.evaluate(() => (document.body.innerText.match(/STUB-TUTOR/g) || []).length);
const inputReady = c => c.waitForFunction(() => { const t = [...document.querySelectorAll('textarea')].pop(); return t && !t.disabled; }, null, { timeout: 60000 });
async function sendChat(c, text) {
  const n = await replies(c); await inputReady(c);
  const ta = c.locator('textarea').last(); await ta.fill(text); await ta.press('Enter');
  await c.waitForFunction(n => (document.body.innerText.match(/STUB-TUTOR/g) || []).length >= n, n + 1, { timeout: 90000 });
  await inputReady(c);
}
async function parentLogin(p) {
  await p.goto(F.ui + '/'); await p.getByPlaceholder(/password/i).fill(F.parent_password);
  await p.getByRole('button', { name: /Enter as Parent/ }).click(); await p.waitForURL(/setup|pod/, { timeout: 30000 });
}
// The one-time "Meet Bede" introduction can take several seconds to render
// on a slow runner. Wait for either its button or Bede's first message
// rather than giving up after a fixed few seconds.
async function passIntro(c) {
  const go = c.getByRole('button', { name: "Let's begin!" });
  for (let i = 0; i < 150; i++) {
    if (await go.isVisible().catch(() => false)) { await go.click(); return; }
    if (await c.evaluate(() => /STUB-TUTOR/.test(document.body.innerText)).catch(() => false)) return;
    await c.waitForTimeout(200);
  }
}
async function childLogin(c, name) {
  await c.goto(F.ui + '/?returnTo=' + encodeURIComponent('/session?student=' + name));
  await c.getByRole('button', { name: /Student/ }).first().click();
  const nm = c.getByPlaceholder('Emma'); if (await nm.count()) await nm.fill(name);
  await c.getByPlaceholder('Enter PIN').fill(F.learners[name]);
  await c.getByRole('button', { name: /Continue/ }).click(); await c.waitForURL(/session/, { timeout: 30000 });
  await passIntro(c);
  await c.waitForFunction(() => /STUB-TUTOR/.test(document.body.innerText), null, { timeout: 60000 });
}
async function openCoach(p, learner, viaPodSave) {
  await p.goto(F.ui + '/setup'); await p.getByText(learner).first().waitFor({ timeout: 30000 });
  let status = 'not-saved';
  if (viaPodSave) {
    const hitl = p.getByRole('checkbox').last(); if (!(await hitl.isChecked())) await hitl.check();
    const save = p.waitForResponse(r => r.url().includes('/api/pod/configs') && r.request().method() === 'POST', { timeout: 30000 }).catch(() => null);
    await p.getByRole('button', { name: /Open Pod Dashboard|Begin Session with Bede/ }).click();
    const r = await save; status = r ? r.status() : null; await p.waitForURL(/pod|session/, { timeout: 30000 });
  }
  await p.goto(F.ui + '/progress?student=' + encodeURIComponent(learner));
  const card = p.getByRole('region', { name: 'Practice from a graded quiz' }); await card.waitFor({ timeout: 30000 });
  const s = card.getByRole('button', { name: 'Start' }); if (await s.count()) await s.click();
  return { card, status };
}
async function launch(name) {
  if (name === 'webkit') return pw.webkit.launch();
  if (name === 'firefox') return pw.firefox.launch();
  if (name === 'chromium') return pw.chromium.launch();
  return pw.chromium.launch({ channel: name });
}

async function parent(br, bname, i) {
  const who = `parent${i + 1}_${bname}`, learner = LEARNERS[i], file = ['quiz.jpg', 'quiz.png', 'quiz.pdf'][i % 3];
  const ctx = await br.newContext({ viewport: { width: 1366, height: 900 } }); const p = await ctx.newPage(); p.on('dialog', d => d.accept());
  try {
    await step(who, 'sign_in', () => parentLogin(p));
    const { card, status } = await step(who, 'open_practice_coach', () => openCoach(p, learner, true));
    check(who, 'overlapping_pod_save_ok', [200, 201, 204].includes(status), `POST /pod/configs -> ${status}`);
    await card.locator('select').first().selectOption('history');
    await card.getByLabel('Photos or a PDF of the graded pages').setInputFiles(path.join(F.fixtures, file));
    await barrier('start'); await barrier('overlap');
    await step(who, 'upload_and_read', async () => { await card.getByRole('button', { name: 'Read the quiz' }).click(); await card.getByRole('button', { name: 'Confirm and plan practice' }).waitFor({ timeout: 120000 }); });
    const confirm = card.getByRole('button', { name: 'Confirm and plan practice' });
    check(who, 'planning_blocked_while_flagged', await confirm.isDisabled());
    await card.getByLabel("Teacher's correction for Ancient Egypt #2").fill('pharaoh');
    await card.getByRole('button', { name: 'Looks right' }).click();
    await card.getByLabel("Teacher's correction for Ancient Egypt #3").fill('papyrus');
    await step(who, 'review_and_plan', async () => { await confirm.click(); await card.getByRole('button', { name: 'Approve' }).waitFor({ timeout: 60000 }); });
    await barrier('save');
    await step(who, 'approve', async () => { await card.getByRole('button', { name: 'Approve' }).click(); await card.getByText('Approved.').waitFor({ timeout: 60000 }); });
    const s = JSON.parse((await apiCall(p, `/practice/${encodeURIComponent(learner)}/sets?status=approved`)).body);
    check(who, 'approved_set_saved_for_the_right_learner', s.length === 1, `${learner}: approved sets=${s.length}`);
  } catch (e) { check(who, 'journey_completed', false, e.message); await p.screenshot({ path: path.join(OUT, `fail-${who}.png`), fullPage: true }).catch(() => {}); release(['start', 'overlap', 'save']); }
  await waitFile('restarted').catch(() => {});
  await barrier('reopen');
  await step(who, 'reopen_after_restart', async () => {
    await p.reload(); if (await p.getByPlaceholder(/password/i).count()) await parentLogin(p);
    await openCoach(p, learner, false);
    const s = JSON.parse((await apiCall(p, `/practice/${encodeURIComponent(learner)}/sets?status=approved`)).body);
    check(who, 'approved_set_persisted_after_restart', s.length === 1, `approved sets=${s.length}`);
    check(who, 'child_answer_visible_to_parent_after_restart', Object.keys(s[0]?.observed_outcomes || {}).length >= 1, JSON.stringify(Object.keys(s[0]?.observed_outcomes || {})));
  }).catch(() => {});
  await ctx.close();
}

async function child(br, bname, i) {
  const who = `child${i + 1}_${bname}`, name = LEARNERS[i], sibling = LEARNERS[(i + 1) % N];
  const first = i === 0;
  // The first child blocks the app's service worker so the #794 transport retry can be observed with route().
  const ctx = await br.newContext({ viewport: { width: 1180, height: 820 }, ...(first ? { serviceWorkers: 'block' } : {}) });
  const c = await ctx.newPage(); c.on('dialog', d => d.accept());
  let setId = null;
  try {
    await step(who, 'sign_in_and_session_start', () => childLogin(c, name));
    if (first) {
      let seen = 0, aborted = 0;
      await c.route(u => u.pathname.endsWith('/api/tutor/chat'), route => { seen++; if (!aborted) { aborted++; return route.abort('connectionreset'); } return route.continue(); });
      await step(who, 'lesson_turn_with_dropped_connection', () => sendChat(c, 'The river was the Nile.'));
      await c.unrouteAll({ behavior: 'ignoreErrors' });
      check(who, 'client_retry_recovers_dropped_connection', aborted === 1 && seen >= 2 && !/didn't reach me/.test(await c.locator('body').innerText()), `attempts=${seen} aborted=${aborted}`);
    } else if (i === 1) {
      // D-1 (#806): with the app's service worker in control, a one-second
      // network drop while a turn is sent must still deliver the turn. The
      // old worker answered the failed send with a fake 200 and the turn was
      // lost with no message.
      const controlled = await c.evaluate(async () => { await navigator.serviceWorker?.ready; return !!navigator.serviceWorker?.controller; });
      check(who, 'service_worker_in_control', controlled);
      await step(who, 'lesson_turn_through_network_blip', async () => {
        const n = await replies(c); await inputReady(c);
        const ta = c.locator('textarea').last(); await ta.fill('The river was the Nile.');
        await ctx.setOffline(true); await ta.press('Enter');
        await c.waitForTimeout(1000); await ctx.setOffline(false);
        await c.waitForFunction(n => (document.body.innerText.match(/STUB-TUTOR/g) || []).length >= n, n + 1, { timeout: 60000 });
        await inputReady(c);
      });
      check(who, 'turn_survives_network_blip_with_service_worker', true);
    } else {
      await step(who, 'lesson_turn_1', () => sendChat(c, 'The river was the Nile.'));
    }
    await barrier('start'); await barrier('overlap');
    await step(who, 'lesson_turn_overlapped', () => sendChat(c, 'Farmers planted after the flood.'));
    if (N > 1) {
      const a = await apiCall(c, `/pod/configs/${encodeURIComponent(sibling)}`);
      const d = await apiCall(c, `/practice/${encodeURIComponent(sibling)}/delivery`);
      check(who, 'sibling_data_refused', a.status >= 400 && d.status >= 400, `config ${a.status}, practice ${d.status}`);
    }
    await waitFor('save');
    const sec = c.getByRole('region', { name: 'A practice question your parent approved' });
    await step(who, 'receive_approved_practice', async () => {
      for (let k = 0; k < 90 && !setId; k++) { const r = JSON.parse((await apiCall(c, `/practice/${encodeURIComponent(name)}/delivery`)).body || '[]'); if (Array.isArray(r) && r.length) setId = r[0].id; else await c.waitForTimeout(1000); }
      if (!setId) throw new Error('no approved set');
      await c.reload(); await passIntro(c);
      const chk = c.getByRole('button', { name: 'Check for approved practice' }); if (await chk.count()) await chk.click();
      await sec.waitFor({ timeout: 30000 });
    });
    await step(who, 'answer_practice_item', async () => {
      const n = await replies(c);
      const o = c.waitForResponse(r => r.url().includes('/outcomes') && r.request().method() === 'POST', { timeout: 30000 });
      await sec.getByLabel('Your answer').fill('pharaoh'); await sec.getByRole('button', { name: 'Send my answer to Bede' }).click();
      const r = await o; if (r.status() !== 200) throw new Error('outcome ' + r.status());
      await c.waitForFunction(n => (document.body.innerText.match(/STUB-TUTOR/g) || []).length >= n, n + 1, { timeout: 90000 });
    });
  } catch (e) {
    // Screenshots live in an artifact not every reader can download, so say what was on screen.
    const screen = (await c.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400);
    console.log(`SCREEN ${who} at ${c.url()}: ${screen}`);
    check(who, 'journey_completed', false, e.message); await c.screenshot({ path: path.join(OUT, `fail-${who}.png`), fullPage: true }).catch(() => {}); release(['start', 'overlap']); }
  barrier('answer_done');
  if (first) {
    // Restart the service while this child's reply is streaming.
    await waitFor('answer_done'); await inputReady(c).catch(() => {});
    const resp = c.waitForResponse(r => r.url().includes('/api/tutor/chat'), { timeout: 60000 });
    const ta = c.locator('textarea').last(); await ta.fill('What happened after the flood?'); await ta.press('Enter');
    await resp.catch(() => {}); fs.writeFileSync(path.join(CTL, 'restart'), '1'); const tk = now();
    await c.waitForFunction(() => /didn't reach me|lost the connection|went wrong|try again|request failed/i.test(document.body.innerText), null, { timeout: 90000 })
      .then(() => check(who, 'midstream_restart_shows_plain_message', true, `${now() - tk}ms after kill`))
      .catch(() => check(who, 'midstream_restart_shows_plain_message', false, 'nothing shown in 90s'));
  }
  await waitFile('restarted').catch(e => check(who, 'restart_observed', false, e.message));
  await barrier('reopen');
  await step(who, 'reopen_after_restart', async () => {
    await c.reload(); if (!/session/.test(c.url()) || await c.getByPlaceholder('Enter PIN').count()) await childLogin(c, name);
    else { await passIntro(c); }
  }).catch(() => {});
  await step(who, 'lesson_turn_after_restart', () => sendChat(c, 'One more thing about Egypt.')).catch(() => {});
  if (setId) {
    const r = JSON.parse((await apiCall(c, `/practice/${encodeURIComponent(name)}/delivery`)).body || '[]').find(x => x.id === setId);
    check(who, 'answer_persisted_after_restart', r && r.completed_indices.length >= 1, JSON.stringify(r?.completed_indices));
    const again = await apiCall(c, `/practice/${encodeURIComponent(name)}/sets/${setId}/outcomes`, 'POST', { item_index: r?.completed_indices?.[0] ?? 0, response: 'pharaoh' });
    check(who, 'answer_retry_is_idempotent', again.status === 200 && /"already_recorded":\s*true/.test(again.body), `${again.status} ${again.body.slice(0, 80)}`);
  }
  await ctx.close();
}

function pct(a, q) { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.ceil(q * s.length) - 1)] : null; }

(async () => {
  const browsers = [];
  for (const b of F.browsers) {
    const br = await launch(b); browsers.push(br);
    console.log(`browser ${b}: ${br.browserType().name()} ${br.version()}`);
  }
  await Promise.all(F.browsers.flatMap((b, i) => [parent(browsers[i], b, i), child(browsers[i], b, i)]));
  const versions = Object.fromEntries(F.browsers.map((b, i) => [b, `${browsers[i].browserType().name()} ${browsers[i].version()}`]));
  for (const br of browsers) await br.close();
  const byStep = {};
  for (const s of steps.filter(s => s.ok)) (byStep[s.step] ||= []).push(s.ms);
  const latency = Object.fromEntries(Object.entries(byStep).map(([k, v]) => [k, { n: v.length, p50: pct(v, 0.5), p95: pct(v, 0.95), max: Math.max(...v) }]));
  const summary = { sha: F.sha, os: F.os, browsers: versions, users: 2 * N, checks: checks.length, failed_checks: checks.filter(c => !c.ok).length,
    steps: steps.length, failed_steps: steps.filter(s => !s.ok).length, latency_ms: latency };
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ summary, checks, steps }, null, 1));
  console.log('SUMMARY ' + JSON.stringify(summary));
  process.exit(summary.failed_checks || summary.failed_steps ? 1 : 0);
})();
