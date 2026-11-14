// Cross-platform browser journeys (#599/#755). Sample data only.
// Started by run_journeys.py. Every browser in F.browsers runs at once
// against ONE service: per browser, one parent device and one child device.
// Browsers are the real installed ones on the runner: Google Chrome
// (channel "chrome"), Microsoft Edge (channel "msedge"), and on macOS
// Playwright's WebKit build (the Safari engine, NOT Safari itself), and
// Playwright's Firefox build (the Gecko engine, NOT branded Firefox).
//
// F.profile 'mobile' instead runs a smaller set of journeys in Playwright
// DEVICE EMULATION (viewport, user agent, touch). Emulation is not a phone:
// results are labelled 'emulated' and never stand in for a physical device
// (see docs/release/DEVICE_QUALIFICATION.md).
const pw = require('playwright');
const fs = require('fs');
const path = require('path');
const F = JSON.parse(fs.readFileSync(process.env.FIX));
const OUT = F.out, CTL = F.ctl, T0 = Date.now(), now = () => Date.now();
const steps = [], checks = [];
const PROFILE = F.profile || 'desktop';
const N = PROFILE === 'mobile' ? F.devices.length : F.browsers.length, LEARNERS = Object.keys(F.learners);

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
  // Record what the browser itself reports, so an engine-specific failure
  // (a WebKit page crash, a script error) is visible in the job log.
  c.on('pageerror', err => console.log(`PAGEERROR ${who}: ${String(err).slice(0, 300)}`));
  c.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log(`CONSOLE ${who} ${m.type()}: ${m.text().slice(0, 300)}`); });
  c.on('crash', () => console.log(`CRASH ${who} at ${c.url()}`));
  c.on('requestfailed', r => console.log(`REQFAIL ${who} ${r.method()} ${r.url().replace(/^https?:\/\/[^/]+/, '')} ${r.failure()?.errorText || ''}`));
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
  if (setId) try {
    const r = JSON.parse((await apiCall(c, `/practice/${encodeURIComponent(name)}/delivery`)).body || '[]').find(x => x.id === setId);
    check(who, 'answer_persisted_after_restart', r && r.completed_indices.length >= 1, JSON.stringify(r?.completed_indices));
    const again = await apiCall(c, `/practice/${encodeURIComponent(name)}/sets/${setId}/outcomes`, 'POST', { item_index: r?.completed_indices?.[0] ?? 0, response: 'pharaoh' });
    check(who, 'answer_retry_is_idempotent', again.status === 200 && /"already_recorded":\s*true/.test(again.body), `${again.status} ${again.body.slice(0, 80)}`);
  } catch (e) { check(who, 'answer_persisted_after_restart', false, e.message); }
  await ctx.close().catch(() => {});
}


// No horizontal page scroll: a layout that only works at desktop width is a
// usability failure on a phone even when every button still technically works.
const noHorizontalScroll = pg => pg.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);

async function mobileParent(br, dev, i) {
  const who = `parent${i + 1}_${dev.replace(/\s+/g, '_')}`, learner = LEARNERS[i];
  const ctx = await br.newContext({ ...pw.devices[dev] }); const p = await ctx.newPage(); p.on('dialog', d => d.accept());
  try {
    await step(who, 'sign_in', () => parentLogin(p));
    check(who, 'setup_no_horizontal_scroll', await noHorizontalScroll(p));
    const { card, status } = await step(who, 'open_practice_coach', () => openCoach(p, learner, true));
    check(who, 'overlapping_pod_save_ok', [200, 201, 204].includes(status), `POST /pod/configs -> ${status}`);
    check(who, 'progress_no_horizontal_scroll', await noHorizontalScroll(p));
    await card.locator('select').first().selectOption('history');
    await card.getByLabel('Photos or a PDF of the graded pages').setInputFiles(path.join(F.fixtures, ['quiz.jpg', 'quiz.png', 'quiz.pdf'][i % 3]));
    await step(who, 'upload_and_read', async () => { await card.getByRole('button', { name: 'Read the quiz' }).click(); await card.getByRole('button', { name: 'Confirm and plan practice' }).waitFor({ timeout: 120000 }); });
    const confirm = card.getByRole('button', { name: 'Confirm and plan practice' });
    check(who, 'planning_blocked_while_flagged', await confirm.isDisabled());
    await card.getByLabel("Teacher's correction for Ancient Egypt #2").fill('pharaoh');
    await card.getByRole('button', { name: 'Looks right' }).click();
    await card.getByLabel("Teacher's correction for Ancient Egypt #3").fill('papyrus');
    await step(who, 'review_and_plan', async () => { await confirm.click(); await card.getByRole('button', { name: 'Approve' }).waitFor({ timeout: 60000 }); });
    await step(who, 'approve', async () => { await card.getByRole('button', { name: 'Approve' }).click(); await card.getByText('Approved.').waitFor({ timeout: 60000 }); });
    const s = JSON.parse((await apiCall(p, `/practice/${encodeURIComponent(learner)}/sets?status=approved`)).body);
    check(who, 'approved_set_saved_for_the_right_learner', s.length === 1, `${learner}: approved sets=${s.length}`);
    await step(who, 'log_out', async () => {
      await p.goto(F.ui + '/setup'); await p.getByRole('button', { name: 'Log out' }).first().click();
      await p.getByPlaceholder(/password/i).waitFor({ timeout: 30000 });
    });
    // After logging out, going back to the parent pages must not show any
    // learner in the household, and nothing must remain that could
    // authenticate a request. The pages are opened WITHOUT a ?student= in the
    // URL: the login page legitimately echoes a name the visitor typed into
    // the link itself, which is not stored data.
    let shown = [];
    for (const page of ['/setup', '/pod', '/progress']) {
      await p.goto(F.ui + page); await p.waitForLoadState('networkidle').catch(() => {});
      const body = await p.locator('body').innerText();
      shown.push(...LEARNERS.filter(n => body.includes(n)).map(n => `${page}:${n}`));
    }
    const token = await p.evaluate(() => Object.keys(sessionStorage).some(k => { try { return !!JSON.parse(sessionStorage.getItem(k))?.state?.token } catch { return false } }));
    // A roster left in browser storage is stale data even when no page shows it.
    const stored = await p.evaluate(names => { const all = Object.keys(sessionStorage).map(k => sessionStorage.getItem(k)).join(' ') + ' ' + Object.keys(localStorage).map(k => localStorage.getItem(k)).join(' '); return names.filter(n => all.includes(n)); }, LEARNERS);
    check(who, 'logged_out_no_stale_content', !shown.length && !token && !stored.length,
      `learners shown=${JSON.stringify(shown)} stored=${JSON.stringify(stored)} token=${token}`);
  } catch (e) { check(who, 'journey_completed', false, e.message); await p.screenshot({ path: path.join(OUT, `fail-${who}.png`), fullPage: true }).catch(() => {}); }
  await ctx.close();
}

async function mobileChild(br, dev, i) {
  const who = `child${i + 1}_${dev.replace(/\s+/g, '_')}`, name = LEARNERS[i];
  const ctx = await br.newContext({ ...pw.devices[dev] }); const c = await ctx.newPage(); c.on('dialog', d => d.accept());
  c.on('pageerror', err => console.log(`PAGEERROR ${who}: ${String(err).slice(0, 300)}`));
  try {
    await step(who, 'sign_in_and_session_start', () => childLogin(c, name));
    await step(who, 'lesson_turn', () => sendChat(c, 'The river was the Nile.'));
    check(who, 'session_no_horizontal_scroll', await noHorizontalScroll(c));
    const inView = await c.evaluate(() => { const t = [...document.querySelectorAll('textarea')].pop(); if (!t) return false; const r = t.getBoundingClientRect(); return r.bottom <= window.innerHeight + 1 && r.top >= 0; });
    check(who, 'answer_box_visible_after_reply', inView);
  } catch (e) {
    const screen = (await c.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400);
    console.log(`SCREEN ${who} at ${c.url()}: ${screen}`);
    check(who, 'journey_completed', false, e.message); await c.screenshot({ path: path.join(OUT, `fail-${who}.png`), fullPage: true }).catch(() => {}); }
  await ctx.close().catch(() => {});
}


// ── Boundary profile: known failure classes, asserted at the edge ──────────
// Each check names a boundary this codebase has already got wrong or guards
// explicitly (CLAUDE.md, docs/SECURITY.md): an open redirect after login, a
// wrong password reported as an expired session, a rejected token that logs
// out silently, a back button that shows the household after logout, an
// oversized or non-image upload, a double-tapped approval, a blank or
// over-long message, a child reaching parent pages, text at 175%, and the
// account-recovery route staying reachable while the parent is locked out.
const tokenIn = pg => pg.evaluate(() => Object.keys(sessionStorage).some(k => { try { return !!JSON.parse(sessionStorage.getItem(k))?.state?.token } catch { return false } }));
const stubCount = kind => { try { return fs.readFileSync(path.join(OUT, 'stub.jsonl'), 'utf8').split('\n').filter(l => l.includes(`"kind": "${kind}"`)).length; } catch { return 0; } };
const appFetch = (pg, p, method = 'GET', body, auth = true) => pg.evaluate(async ([p, method, body, auth]) => {
  let tok = null; if (auth) for (const k of Object.keys(sessionStorage)) { try { const v = JSON.parse(sessionStorage.getItem(k)); if (v?.state?.token) tok = v.state.token } catch {} }
  const h = { 'Content-Type': 'application/json' }; if (tok) h.Authorization = 'Bearer ' + tok;
  const r = await fetch('/api' + p, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: (await r.text()).slice(0, 300) };
}, [p, method, body, auth]);
const SESSION_ENDED = "Your session ended, so you'll need to sign in again.";

async function boundaryParent(br, bname, i) {
  const who = `parent${i + 1}_${bname}`, learner = LEARNERS[i];
  const fresh = async () => { const ctx = await br.newContext({ viewport: { width: 1366, height: 900 } }); const p = await ctx.newPage(); p.on('dialog', d => d.accept()); return [ctx, p]; };
  const origin = new URL(F.ui).origin;
  try {
    // 1. Open redirect after login (utils/safeRedirect.ts).
    const escaped = [];
    for (const target of ['https://example.invalid/x', '//example.invalid/x', '/\\example.invalid', 'javascript:alert(1)']) {
      const [ctx, p] = await fresh();
      await p.goto(F.ui + '/?returnTo=' + encodeURIComponent(target));
      await p.getByPlaceholder(/password/i).fill(F.parent_password);
      await p.getByRole('button', { name: /Enter as Parent/ }).click();
      await p.waitForURL(u => !/\/$/.test(u.pathname) || u.origin !== origin, { timeout: 30000 }).catch(() => {});
      const u = new URL(p.url()); if (u.origin !== origin) escaped.push(`${target} -> ${u.origin}`);
      await ctx.close();
    }
    check(who, 'open_redirect_refused', !escaped.length, escaped.join('; '));

    // 2. A wrong password is a plain error, never "your session ended", and leaves no token.
    {
      const [ctx, p] = await fresh();
      await p.goto(F.ui + '/'); await p.getByPlaceholder(/password/i).fill('not-the-password-' + i);
      const resp = p.waitForResponse(r => r.url().includes('/api/auth/login'), { timeout: 30000 });
      await p.getByRole('button', { name: /Enter as Parent/ }).click(); const r = await resp;
      await p.waitForTimeout(800);
      const body = await p.locator('body').innerText();
      check(who, 'wrong_password_plain_error', r.status() === 401 && new URL(p.url()).pathname === '/' && !(await tokenIn(p)) && !body.includes(SESSION_ENDED) && /invalid|incorrect|wrong|failed/i.test(body),
        `status=${r.status()} path=${new URL(p.url()).pathname} expiredNotice=${body.includes(SESSION_ENDED)}`);
      await ctx.close();
    }

    // 3. A token the server rejects logs out WITH a notice (utils/logoutNotice.ts), not silently.
    {
      const [ctx, p] = await fresh();
      await parentLogin(p);
      await p.evaluate(() => { for (const k of Object.keys(sessionStorage)) { try { const v = JSON.parse(sessionStorage.getItem(k)); if (v?.state?.token) { v.state.token = 'invalid.token.value'; sessionStorage.setItem(k, JSON.stringify(v)); } } catch {} } });
      await p.goto(F.ui + '/setup');
      const shown = await p.getByText(SESSION_ENDED).waitFor({ timeout: 30000 }).then(() => true).catch(() => false);
      check(who, 'invalid_token_logs_out_with_notice', shown && !(await tokenIn(p)), `notice=${shown}`);
      await ctx.close();
    }

    // 4. Back after logout must not bring the household back on screen.
    {
      const [ctx, p] = await fresh();
      // Setup is where a returning parent's household loads (GET /pod/configs).
      await parentLogin(p); await p.goto(F.ui + '/setup'); await p.getByText(learner).first().waitFor({ timeout: 30000 });
      await p.getByRole('button', { name: 'Log out' }).first().click(); await p.getByPlaceholder(/password/i).waitFor({ timeout: 30000 });
      await p.goBack().catch(() => {}); await p.waitForTimeout(1500);
      const body = await p.locator('body').innerText();
      const shown = LEARNERS.filter(n => body.includes(n));
      check(who, 'back_after_logout_shows_no_household', !shown.length && !(await tokenIn(p)), `shown=${JSON.stringify(shown)} at ${new URL(p.url()).pathname}`);
      await ctx.close();
    }

    // 5-7. Upload boundaries and a double-tapped approval, on the real Practice Coach.
    const [ctx, p] = await fresh();
    await step(who, 'sign_in', () => parentLogin(p));
    // The Practice Coach card appears once the parent turns it on in Setup (the pod save).
    const { card } = await step(who, 'open_practice_coach', () => openCoach(p, learner, true));
    await card.locator('select').first().selectOption('history');
    const input = card.getByLabel('Photos or a PDF of the graded pages');
    const readsBefore = stubCount('reading');
    await input.setInputFiles(path.join(F.fixtures, 'oversize.jpg'));
    const big = await card.getByText(/larger than 25 MB/).waitFor({ timeout: 10000 }).then(() => true).catch(() => false);
    check(who, 'oversize_upload_refused_before_send', big && stubCount('reading') === readsBefore, `message=${big}`);

    await input.setInputFiles(path.join(F.fixtures, 'not-an-image.png'));
    const sent = p.waitForResponse(r => /\/api\/practice\//.test(r.url()) && r.request().method() === 'POST', { timeout: 30000 }).catch(() => null);
    await card.getByRole('button', { name: 'Read the quiz' }).click().catch(() => {});
    const r = await sent; await p.waitForTimeout(1000);
    const reviewing = await card.getByRole('button', { name: 'Confirm and plan practice' }).count();
    check(who, 'unsupported_upload_refused_without_reading', !reviewing && stubCount('reading') === readsBefore && (r === null || r.status() >= 400),
      `status=${r ? r.status() : 'not sent'} reads=${stubCount('reading') - readsBefore}`);

    await input.setInputFiles(path.join(F.fixtures, 'quiz.png'));
    await step(who, 'upload_and_read', async () => { await card.getByRole('button', { name: 'Read the quiz' }).click(); await card.getByRole('button', { name: 'Confirm and plan practice' }).waitFor({ timeout: 120000 }); });
    await card.getByLabel("Teacher's correction for Ancient Egypt #2").fill('pharaoh');
    await card.getByRole('button', { name: 'Looks right' }).click();
    await card.getByLabel("Teacher's correction for Ancient Egypt #3").fill('papyrus');
    await step(who, 'review_and_plan', async () => { await card.getByRole('button', { name: 'Confirm and plan practice' }).click(); await card.getByRole('button', { name: 'Approve' }).waitFor({ timeout: 60000 }); });
    // The card may say "Approved." more than once after a double tap; the
    // assertion that matters is what the server holds, so wait for the first.
    await step(who, 'double_tap_approve', async () => { await card.getByRole('button', { name: 'Approve' }).dblclick(); await card.getByText('Approved.').first().waitFor({ timeout: 60000 }); });
    await p.waitForTimeout(1500);
    const shown = await card.getByText('Approved.').count();
    const sets = JSON.parse((await apiCall(p, `/practice/${encodeURIComponent(learner)}/sets?status=approved`)).body);
    check(who, 'double_approve_single_set', sets.length === 1, `approved sets=${sets.length} "Approved." shown ${shown}x`);
    await ctx.close();
  } catch (e) { check(who, 'journey_completed', false, e.message); }
}

async function boundaryChild(br, bname, i) {
  const who = `child${i + 1}_${bname}`, name = LEARNERS[i], sibling = LEARNERS[(i + 1) % LEARNERS.length];
  const ctx = await br.newContext({ viewport: { width: 1180, height: 820 } }); const c = await ctx.newPage(); c.on('dialog', d => d.accept());
  let chatPosts = 0; c.on('request', r => { if (r.url().includes('/api/tutor/chat') && r.method() === 'POST') chatPosts++; });
  try {
    await step(who, 'sign_in_and_session_start', () => childLogin(c, name));
    // A blank message is not sent.
    await inputReady(c); const before = chatPosts;
    const ta = c.locator('textarea').last(); await ta.fill('   \n  '); await ta.press('Enter'); await c.waitForTimeout(2000);
    check(who, 'blank_message_not_sent', chatPosts === before, `posts=${chatPosts - before}`);
    // Longer than the API accepts (child_message max 2000): never a silent
    // hang, never blamed on the connection, and the words are not lost.
    await ta.fill('');
    const long = 'The river Nile flooded every year and farmers planted after the flood. '.repeat(40).slice(0, 2600);
    const n = await replies(c); await ta.fill(long); await ta.press('Enter');
    await c.waitForFunction(n => (document.body.innerText.match(/STUB-TUTOR/g) || []).length > n || /couldn't|could not|too long|failed|try again|check your connection/i.test(document.body.innerText), n, { timeout: 60000 }).catch(() => {});
    await c.waitForTimeout(1000);
    const body = await c.locator('body').innerText();
    const replied = (body.match(/STUB-TUTOR/g) || []).length > n;
    const blamesConnection = /connection/i.test(body.split('STUB-TUTOR').pop());
    const kept = (await ta.inputValue()).length > 0 || body.includes(long.slice(0, 200));
    const usable = await c.evaluate(() => { const t = [...document.querySelectorAll('textarea')].pop(); return !!t && !t.disabled; });
    check(who, 'overlong_message_handled_plainly', usable && (replied || (!blamesConnection && kept)),
      `replied=${replied} blamesConnection=${blamesConnection} wordsKept=${kept} usable=${usable}`);
    // A child cannot use the parent's pages or API.
    const list = await appFetch(c, '/pod/configs');
    const other = await appFetch(c, `/practice/${encodeURIComponent(sibling)}/sets?status=approved`);
    await c.goto(F.ui + '/setup'); await c.waitForTimeout(1500);
    const page = await c.locator('body').innerText();
    check(who, 'child_cannot_open_parent_pages', list.status >= 400 && other.status >= 400 && !page.includes('Practice from a graded quiz') && !page.includes(sibling),
      `GET /pod/configs ${list.status}, sibling sets ${other.status}, sibling shown=${page.includes(sibling)}`);
    await ctx.close();
    // Text at the largest step (175%) on a phone-width screen keeps the page from scrolling sideways.
    const ctx2 = await br.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
    await ctx2.addInitScript(() => { try { localStorage.setItem('bede-text-scale', '175') } catch {} });
    const c2 = await ctx2.newPage(); c2.on('dialog', d => d.accept());
    c2.on('pageerror', err => console.log(`PAGEERROR ${who}@175%: ${String(err).slice(0, 300)}`));
    c2.on('crash', () => console.log(`CRASH ${who}@175% at ${c2.url()}`));
    c2.on('console', m => { if (m.type() === 'error') console.log(`CONSOLE ${who}@175% error: ${m.text().slice(0, 300)}`); });
    const chat175 = [];
    c2.on('response', r => { if (r.url().includes('/api/tutor/chat')) chat175.push(r.status()); });
    c2.on('requestfailed', r => { if (r.url().includes('/api/tutor/chat')) chat175.push(`failed:${r.failure()?.errorText || ''}`); });
    // What the page itself showed, not the first context's (already closed) screen.
    const describe = async (pg, label) => {
      // innerText is what is rendered; textContent includes what is clipped or
      // hidden. Bede's reply in textContent but not innerText means it arrived
      // and is not visible; in neither means it never arrived.
      const d = await pg.evaluate(() => {
        const list = [...document.querySelectorAll('.overflow-y-auto')].map(e => Math.round(e.getBoundingClientRect().height));
        return { text: document.body.innerText.replace(/\s+/g, ' ').slice(0, 300), root: document.getElementById('root')?.innerHTML.length ?? -1,
          fontSize: getComputedStyle(document.documentElement).fontSize, replyRendered: /STUB-TUTOR/.test(document.body.innerText),
          replyInDom: /STUB-TUTOR/.test(document.body.textContent || ''), scrollAreaHeights: list, viewport: [innerWidth, innerHeight] };
      }).catch(e => ({ error: String(e).slice(0, 200) }));
      console.log(`SCREEN ${who}${label} at ${pg.url()}: ${JSON.stringify(d)} chatResponses=${JSON.stringify(label === '@175%' ? chat175 : 'n/a')}`);
    };
    try {
      await step(who, 'sign_in_at_175_percent', () => childLogin(c2, name));
    } catch (e) {
      await describe(c2, '@175%');
      // Diagnosis only (not a check): the same phone-sized, touch context
      // without the 175% setting, to tell a text-scale fault from an engine one.
      const ctl = await br.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true }); const cp = await ctl.newPage();
      const ok = await childLogin(cp, name).then(() => true).catch(() => false);
      console.log(`CONTROL ${who} phone-size without 175%: sign-in ${ok ? 'succeeded' : 'failed'}`);
      if (!ok) await describe(cp, '@control');
      await ctl.close().catch(() => {});
      await ctx2.close().catch(() => {});
      throw e;
    }
    const scale = await c2.evaluate(() => getComputedStyle(document.documentElement).fontSize);
    check(who, 'text_scale_175_no_horizontal_scroll', await noHorizontalScroll(c2), `root font-size ${scale}`);
    await ctx2.close();
  } catch (e) {
    if (!c.isClosed()) {
      const screen = (await c.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300);
      console.log(`SCREEN ${who} at ${c.url()}: ${screen}`);
    }
    check(who, 'journey_completed', false, e.message); await ctx.close().catch(() => {});
  }
}

// Runs LAST and once: locking the parent out would break every other journey.
async function boundaryLockout(br) {
  const who = 'lockout';
  const ctx = await br.newContext(); const p = await ctx.newPage();
  try {
    await p.goto(F.ui + '/');
    let locked = null, tries = 0;
    for (; tries < 15 && !locked; tries++) {
      const r = await appFetch(p, '/auth/login', 'POST', { role: 'parent', credential: 'wrong-' + tries }, false);
      if (r.status === 429) locked = r;
    }
    check(who, 'parent_locked_after_repeated_failures', !!locked, `after ${tries} attempts: ${locked ? locked.body.slice(0, 80) : 'never locked'}`);
    const right = await appFetch(p, '/auth/login', 'POST', { role: 'parent', credential: F.parent_password }, false);
    check(who, 'locked_parent_refused_even_with_right_password', right.status === 429, `status=${right.status}`);
    // The burst that tripped the lockout must not also block the way back in.
    const rec = await appFetch(p, '/auth/recovery/methods', 'GET', null, false);
    check(who, 'recovery_reachable_while_locked', rec.status === 200, `GET /auth/recovery/methods ${rec.status}`);
  } catch (e) { check(who, 'journey_completed', false, e.message); }
  await ctx.close();
}

// Every check a complete run must produce. A journey that stops early writes
// fewer checks than it should, and a check that never ran is not a pass: the
// run fails if any of these is missing, not only if one recorded ok=false.
function expectedChecks() {
  const out = [];
  if (PROFILE === 'boundary') {
    F.browsers.forEach((b, i) => {
      for (const c of ['open_redirect_refused', 'wrong_password_plain_error', 'invalid_token_logs_out_with_notice', 'back_after_logout_shows_no_household',
        'oversize_upload_refused_before_send', 'unsupported_upload_refused_without_reading', 'double_approve_single_set']) out.push([`parent${i + 1}_${b}`, c]);
      for (const c of ['blank_message_not_sent', 'overlong_message_handled_plainly', 'child_cannot_open_parent_pages', 'text_scale_175_no_horizontal_scroll']) out.push([`child${i + 1}_${b}`, c]);
    });
    for (const c of ['parent_locked_after_repeated_failures', 'locked_parent_refused_even_with_right_password', 'recovery_reachable_while_locked']) out.push(['lockout', c]);
    return out;
  }
  if (PROFILE === 'mobile') {
    F.devices.forEach((dev, i) => {
      const d = dev.replace(/\s+/g, '_');
      for (const c of ['setup_no_horizontal_scroll', 'overlapping_pod_save_ok', 'progress_no_horizontal_scroll', 'planning_blocked_while_flagged',
        'approved_set_saved_for_the_right_learner', 'logged_out_no_stale_content']) out.push([`parent${i + 1}_${d}`, c]);
      for (const c of ['session_no_horizontal_scroll', 'answer_box_visible_after_reply']) out.push([`child${i + 1}_${d}`, c]);
    });
    return out;
  }
  F.browsers.forEach((b, i) => {
    for (const c of ['overlapping_pod_save_ok', 'planning_blocked_while_flagged', 'approved_set_saved_for_the_right_learner',
      'approved_set_persisted_after_restart', 'child_answer_visible_to_parent_after_restart']) out.push([`parent${i + 1}_${b}`, c]);
    const child = [];
    if (i === 0) child.push('client_retry_recovers_dropped_connection', 'midstream_restart_shows_plain_message');
    if (i === 1) child.push('service_worker_in_control', 'turn_survives_network_blip_with_service_worker');
    if (N > 1) child.push('sibling_data_refused');
    child.push('answer_persisted_after_restart', 'answer_retry_is_idempotent');
    for (const c of child) out.push([`child${i + 1}_${b}`, c]);
  });
  return out;
}

function pct(a, q) { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.ceil(q * s.length) - 1)] : null; }

(async () => {
  const browsers = [];
  for (const b of F.browsers) {
    const br = await launch(b); browsers.push(br);
    console.log(`browser ${b}: ${br.browserType().name()} ${br.version()}`);
  }
  if (PROFILE === 'mobile') {
    // Each emulated device runs on the engine its descriptor names (WebKit
    // for iPhone/iPad, Chromium for Android), never on a substitute.
    const engineOf = dev => pw.devices[dev].defaultBrowserType;
    const brFor = dev => { const k = F.browsers.indexOf(engineOf(dev)); if (k < 0) throw new Error(`no ${engineOf(dev)} browser launched for ${dev}`); return browsers[k]; };
    await Promise.all(F.devices.flatMap((dev, i) => [mobileParent(brFor(dev), dev, i), mobileChild(brFor(dev), dev, i)]));
  } else if (PROFILE === 'boundary') {
    await Promise.all(F.browsers.flatMap((b, i) => [boundaryParent(browsers[i], b, i), boundaryChild(browsers[i], b, i)]));
    await boundaryLockout(browsers[0]);
  } else {
    await Promise.all(F.browsers.flatMap((b, i) => [parent(browsers[i], b, i), child(browsers[i], b, i)]));
  }
  const versions = Object.fromEntries(F.browsers.map((b, i) => [b, `${browsers[i].browserType().name()} ${browsers[i].version()}`]));
  for (const br of browsers) await br.close();
  const have = new Set(checks.map(c => `${c.user}|${c.check}`));
  const missing = expectedChecks().filter(([u, c]) => !have.has(`${u}|${c}`)).map(([u, c]) => `${u}/${c}`);
  for (const m of missing) console.log(`MISSING ${m}`);
  const byStep = {};
  for (const s of steps.filter(s => s.ok)) (byStep[s.step] ||= []).push(s.ms);
  const latency = Object.fromEntries(Object.entries(byStep).map(([k, v]) => [k, { n: v.length, p50: pct(v, 0.5), p95: pct(v, 0.95), max: Math.max(...v) }]));
  const summary = { sha: F.sha, os: F.os, os_detail: F.os_detail, profile: PROFILE, evidence: PROFILE === 'mobile' ? 'emulated' : PROFILE === 'boundary' ? 'boundary' : 'desktop-browser',
    devices: PROFILE === 'mobile' ? F.devices : undefined, playwright: require('playwright/package.json').version,
    browsers: versions, users: 2 * N, checks: checks.length, failed_checks: checks.filter(c => !c.ok).length,
    expected_checks: expectedChecks().length, missing_checks: missing,
    steps: steps.length, failed_steps: steps.filter(s => !s.ok).length, latency_ms: latency };
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ summary, checks, steps }, null, 1));
  console.log('SUMMARY ' + JSON.stringify(summary));
  process.exit(summary.failed_checks || summary.failed_steps || missing.length ? 1 : 0);
})();
