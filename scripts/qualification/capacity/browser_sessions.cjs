// One step of the capacity run's browser part: N real Chromium sessions at
// once against ONE Bede backend, each a full child session. Started by
// run_capacity.py with FIX pointing at a JSON file:
//   { sessions: [{ name, pin, ui }], window_s, think_s, out, step }
// Each session's `ui` is its own relay port, so each arrives at Bede from its
// own address (relay.py). Sample data only.
//
// Per session: sign in, lesson turns for window_s (timed: first words on
// screen, answer box usable again), one approved practice answer through the
// app's own practice card after a reload, then a final reload that must land
// back in the lesson. Uses the journeys' own child steps (child_steps.cjs) so
// both drive the app the same way.
const pw = require('playwright');
const fs = require('fs');
const path = require('path');
const childSteps = require('../browser_journeys/child_steps.cjs');

const F = JSON.parse(fs.readFileSync(process.env.FIX));
// A stray rejection inside one session must not end the other sessions' run.
process.on('unhandledRejection', e => console.error('UNHANDLED', String(e).split('\n')[0]));
const learners = Object.fromEntries(F.sessions.map(s => [s.name, s.pin]));
const MESSAGES = ['The river was the Nile.', 'Farmers planted after the flood.', 'They wrote on papyrus.', 'The pharaoh ruled Egypt.'];

function classify(err) {
  const m = String(err && err.message || err);
  if (/Timeout/i.test(m)) return 'timeout';
  return 'dropped';
}

async function session(br, s, i) {
  const S = childSteps({ ui: s.ui, learners });
  const out = { name: s.name, turns: [], answers: [], statuses: {}, errors: [], reloads: [] };
  const ctx = await br.newContext({ viewport: { width: 1180, height: 820 }, ignoreHTTPSErrors: true });
  const c = await ctx.newPage(); c.on('dialog', d => d.accept());
  c.on('response', r => {
    const u = r.url();
    if (!u.includes('/api/')) return;
    const k = String(r.status()); out.statuses[k] = (out.statuses[k] || 0) + 1;
  });
  c.on('crash', () => out.errors.push('page crashed'));
  const t0 = Date.now();
  try {
    await S.childLogin(c, s.name);
    out.signed_in_ms = Date.now() - t0;
  } catch (e) {
    out.errors.push('sign in: ' + String(e.message).split('\n')[0].slice(0, 200));
    await ctx.close().catch(() => {});
    return out;
  }
  const end = Date.now() + F.window_s * 1000;
  let n = 0, answered = false;
  while (Date.now() < end) {
    const before = await S.replies(c).catch(() => null);
    try {
      const t = await S.sendChat(c, MESSAGES[n % MESSAGES.length]);
      const after = await S.replies(c).catch(() => null);
      out.turns.push({ outcome: 'ok', first_s: t.first_ms / 1000, done_s: t.done_ms / 1000, t: Date.now() / 1000,
        duplicated: before !== null && after !== null && after - before > 1 });
    } catch (e) {
      out.turns.push({ outcome: classify(e), error: String(e.message).split('\n')[0].slice(0, 160), t: Date.now() / 1000 });
    }
    n++;
    if (!answered && n === 2) {
      answered = true;
      // The approved practice question, through the app's own card, after a reload.
      try {
        await c.reload(); await S.passIntro(c);
        const chk = c.getByRole('button', { name: 'Check for approved practice' }); if (await chk.count()) await chk.click();
        const sec = c.getByRole('region', { name: 'A practice question your parent approved' });
        await sec.waitFor({ timeout: 30000 });
        const o = c.waitForResponse(r => r.url().includes('/outcomes') && r.request().method() === 'POST', { timeout: 30000 });
        o.catch(() => {}); // if the steps below throw, that error is the one recorded
        await sec.getByLabel('Your answer').fill('pharaoh'); await sec.getByRole('button', { name: 'Send my answer to Bede' }).click();
        const r = await o; let body = {}; try { body = await r.json(); } catch {}
        const m = r.url().match(/\/practice\/[^/]+\/sets\/(\d+)\/outcomes/);
        out.answers.push({ status: r.status(), set_id: m ? Number(m[1]) : null, item: r.request().postDataJSON()?.item_index, already_recorded: !!body.already_recorded });
        out.reloads.push({ at: 'practice', ok: true });
      } catch (e) {
        out.answers.push({ status: null, error: String(e.message).split('\n')[0].slice(0, 160) });
      }
    }
    await c.waitForTimeout(F.think_s * 1000);
  }
  try {
    await c.reload();
    const ok = await S.stillInLesson(c);
    out.reloads.push({ at: 'end', ok });
    if (!ok) out.errors.push('reload left the lesson');
  } catch (e) { out.reloads.push({ at: 'end', ok: false }); out.errors.push('final reload: ' + String(e.message).slice(0, 160)); }
  await ctx.close().catch(() => {});
  return out;
}

(async () => {
  const br = await pw.chromium.launch(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {});
  const results = await Promise.all(F.sessions.map((s, i) => session(br, s, i).catch(e => ({ name: s.name, turns: [], answers: [], statuses: {}, errors: [String(e).slice(0, 200)] }))));
  const version = br.version();
  await br.close();
  fs.writeFileSync(path.join(F.out, `browser-step-${F.step}.json`), JSON.stringify({ chromium: version, playwright: require('playwright/package.json').version, sessions: results }));
  process.exit(0);
})().catch(e => { console.error(e); process.exit(2); });
