// The child-device steps shared by the browser journeys (journeys.cjs) and the
// capacity run (../capacity/browser_sessions.cjs), so both drive the app the
// same way. F needs `ui` (the app's address) and `learners` (name -> PIN).
// Sample data only.
module.exports = function childSteps(F) {
  const replies = c => c.evaluate(() => (document.body.innerText.match(/STUB-TUTOR/g) || []).length);
  const inputReady = c => c.waitForFunction(() => { const t = [...document.querySelectorAll('textarea')].pop(); return t && !t.disabled; }, null, { timeout: 60000 });
  // Returns how long the reply took: first_ms when Bede's first words appear
  // (the stub's first chunk carries the STUB-TUTOR marker), done_ms when the
  // answer box is usable again. The journeys ignore it; the capacity run
  // records it.
  async function sendChat(c, text) {
    const n = await replies(c); await inputReady(c);
    const ta = c.locator('textarea').last(); await ta.fill(text);
    const t0 = Date.now(); await ta.press('Enter');
    await c.waitForFunction(n => (document.body.innerText.match(/STUB-TUTOR/g) || []).length >= n, n + 1, { timeout: 90000 });
    const first_ms = Date.now() - t0;
    await inputReady(c);
    return { first_ms, done_ms: Date.now() - t0 };
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
  // After a reload, is this child still in the lesson or back at sign-in? The
  // login page's own URL carries ?returnTo=%2Fsession…, so test the PATH, and
  // wait for one of the two screens to render before deciding.
  async function stillInLesson(c) {
    await c.waitForFunction(() => document.querySelector('textarea') || document.querySelector('input[placeholder="Enter PIN"]') ||
      [...document.querySelectorAll('button')].some(b => /Student|Let's begin!/.test(b.textContent)), null, { timeout: 30000 }).catch(() => {});
    return new URL(c.url()).pathname.startsWith('/session') && !(await c.getByPlaceholder('Enter PIN').count());
  }
  return { replies, inputReady, sendChat, passIntro, childLogin, stillInLesson };
};
