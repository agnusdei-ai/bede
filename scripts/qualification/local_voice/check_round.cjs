// One child plays a Sound Time round in the real app, in real Chromium, and
// this records what was spoken and how (sample data only). Run by
// run_local_voice_check.py once per voice case; prints one JSON line.
//
// Records: every request the page made (so anything leaving the machine is
// seen), every /api/tutor/speak answer, every <audio> play() and its result,
// every call to the browser's own speechSynthesis.speak, and how far the
// round got with which prompt and feedback on screen.
const pw = require('playwright');

const F = JSON.parse(process.env.ROUND_FIXTURE);

(async () => {
  const out = { requests: [], speak: [], speakTexts: [], plays: [], browserVoice: [], lines: [], feedback: [], steps: [], tapped: [] };
  const browser = await pw.chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1024, height: 900 } })).newPage();
  await page.addInitScript(() => {
    window.__browserVoice = [];
    window.__plays = [];
    if (window.speechSynthesis) {
      const real = window.speechSynthesis.speak.bind(window.speechSynthesis);
      window.speechSynthesis.speak = (u) => { window.__browserVoice.push(String(u && u.text)); return real(u); };
    }
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      const entry = { src: String(this.currentSrc || this.src).slice(0, 30), ok: null };
      window.__plays.push(entry);
      const p = play.call(this);
      p.then(() => { entry.ok = true; }, (e) => { entry.ok = false; entry.err = String(e && e.name); });
      return p;
    };
  });
  // blob: and data: URLs are the page's own memory, not the network.
  page.on('request', (r) => { const u = r.url(); if (/^(blob|data):/.test(u)) return;
    // The exact text of every line sent to Bede's voice, so the check can
    // show it is only the round's fixed lines and Bede's own reply.
    if (u.includes('/api/tutor/speak')) { try { out.speakTexts.push(JSON.parse(r.postData() || '{}').text); } catch { out.speakTexts.push('<unreadable>'); } }
    const p = new URL(u); out.requests.push(p.host + ' ' + r.method() + ' ' + p.pathname); });
  page.on('response', async (r) => {
    if (!r.url().includes('/api/tutor/speak')) return;
    const body = await r.body().catch(() => Buffer.alloc(0));
    out.speak.push({ status: r.status(), type: r.headers()['content-type'] || null,
      configured: r.headers()['x-tts-configured'] || null,
      // The page reads the body into a blob, so Playwright often cannot; the
      // declared length is what the server sent.
      bytes: Number(r.headers()['content-length'] || body.length) });
  });
  const step = (s) => out.steps.push(s);
  try {
    await page.goto(F.ui + '/?returnTo=' + encodeURIComponent('/session?student=' + F.name));
    await page.getByRole('button', { name: /Student/ }).first().click();
    const nm = page.getByPlaceholder('Emma'); if (await nm.count()) await nm.fill(F.name);
    await page.getByPlaceholder('Enter PIN').fill(F.pin);
    await page.getByRole('button', { name: /Continue/ }).click();
    await page.waitForURL(/session/, { timeout: 30000 });
    step('signed_in');
    const go = page.getByRole('button', { name: "Let's begin!" });
    for (let i = 0; i < 100 && !(await page.getByRole('dialog', { name: 'Sound Time' }).count()); i++) {
      if (await go.isVisible().catch(() => false)) await go.click();
      await page.waitForTimeout(200);
    }
    const round = page.getByRole('dialog', { name: 'Sound Time' });
    await round.waitFor({ timeout: 60000 });
    step('round_open');
    const line = async () => (await page.getByTestId('phonics-line').textContent().catch(() => '') || '').trim();
    await page.waitForFunction(() => (document.querySelector('[data-testid="phonics-line"]')?.textContent || '').trim().length > 0, null, { timeout: 30000 });
    out.lines.push(await line());
    await page.waitForTimeout(1500); // let the Watch line be spoken (or not)
    await round.getByRole('button', { name: 'Let’s try one' }).click();
    step('together');
    const FEEDBACK = ['Yes, that’s it!', 'Let’s look again. Try once more.', 'Here it is. Tap Next when you are ready.'];
    for (let i = 0; i < 24; i++) {
      if (!(await round.count())) { step('closed'); break; }
      const text = await round.innerText().catch(() => '');
      if (text.includes('You finished Sound Time!')) { step('finished'); break; }
      const l = await line(); if (l && out.lines[out.lines.length - 1] !== l) out.lines.push(l);
      const choice = round.getByRole('group').getByRole('button', { disabled: false });
      if (await choice.count()) {
        // What the child chose, so the check can show it was never spoken.
        out.tapped.push(((await choice.first().getAttribute('aria-label').catch(() => null))
          || (await choice.first().innerText().catch(() => '')) || '').trim());
        await choice.first().click({ timeout: 5000 }).catch(() => {});
        await page.waitForFunction((fb) => fb.some((f) => document.body.innerText.includes(f)), FEEDBACK, { timeout: 15000 }).catch(() => {});
        const after = await round.innerText().catch(() => '');
        const seen = FEEDBACK.find((f) => after.includes(f)); if (seen) out.feedback.push(seen);
      }
      const next = round.getByRole('button', { name: /^(Next|Let’s try one)$/, disabled: false });
      if (await next.count()) { await next.first().click({ timeout: 5000 }).catch(() => {}); step('next'); }
      await page.waitForTimeout(400);
    }
    // Back in the chat, the child writes to Bede: the reply goes down the
    // chat's own narration path, which a round turn deliberately skips.
    const back = page.getByRole('button', { name: 'Back to Bede' });
    if (await back.count()) await back.first().click({ timeout: 5000 }).catch(() => {});
    const before = await page.evaluate(() => (document.body.innerText.match(/STUB-TUTOR/g) || []).length);
    const box = page.locator('textarea').last();
    await page.waitForFunction(() => { const t = [...document.querySelectorAll('textarea')].pop(); return t && !t.disabled; }, null, { timeout: 30000 });
    await box.fill('I liked the cat one.'); await box.press('Enter');
    await page.waitForFunction((n) => (document.body.innerText.match(/STUB-TUTOR/g) || []).length > n, before, { timeout: 60000 });
    step('chat_reply');
    await page.waitForTimeout(2500); // narration of the reply, or silence
  } catch (e) {
    out.error = String(e).split('\n')[0];
    out.screen = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400);
  }
  out.browserVoice = await page.evaluate(() => window.__browserVoice || []).catch(() => ['<unreadable>']);
  out.plays = await page.evaluate(() => window.__plays || []).catch(() => []);
  await browser.close();
  console.log(JSON.stringify(out));
})();
