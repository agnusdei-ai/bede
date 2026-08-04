// ── Where this form sends ─────────────────────────────────────────────
// Preferred path: the demo API's own POST /feedback, which already
// routes to the operator's inbox through Resend. That endpoint needs a
// token, but the demo's anonymous entry (POST /auth/demo-code) is public
// by design, so a website visitor can get one the same way a demo
// visitor does — mint a code, exchange it for a demo_code JWT, submit.
// agnusdei.io and www.agnusdei.io are already in the API's CORS_ORIGINS
// (render.yaml), so no backend change is required for this to work.
//
// Paste the demo API's base URL below to turn that on — the same value
// as the VITE_DEMO_API_BASE repo variable the demo build uses, e.g.
// 'https://bede-demo-api-XXXX.onrender.com'. No build step; this file
// is served as-is.
//
// Leave it '' (or if the API is unreachable, cold, or has no
// FEEDBACK_EMAIL configured) and the form falls back to composing an
// email in the visitor's own mail client instead, so it is never a dead
// button either way.
//
// If you DO set this, also add that Render origin to site/_headers'
// connect-src for this page — the site's Content-Security-Policy only
// allows 'self' by default, and a CSP-blocked fetch here still degrades
// gracefully to the mailto fallback (the catch block below), but the
// visitor's answers would go out by email every time instead of the
// faster in-app path you just turned on.
//
// Lives in its own file (not an inline <script> in feedback/index.html)
// so the site's CSP (site/_headers) can set script-src 'self' with no
// 'unsafe-inline' exception.
const API_BASE = '';
const FEEDBACK_TO = 'info@agnusdei.ai';
// mailto URLs get truncated by some mail clients past roughly 2000
// characters, which would silently eat the end of a long answer. Warn
// rather than let that happen quietly.
const MAILTO_SAFE_LENGTH = 1900;

const form = document.getElementById('feedback-form');
const note = document.getElementById('form-note');

const label = (name) => ({
  stage: 'Where they are with Bede', stages: 'Stages taught',
  subjects: 'Subjects that matter most', socratic: 'Socratic questioning',
  faith: 'Faith fit', curriculum: 'Curriculum already in use',
  commitment: 'Parent commitment', progress: 'Wanted in progress reporting',
  concerns: 'Safety / privacy / screens', missing: 'The one thing',
  name: 'Name', email: 'Email',
})[name] || name;

const button = form.querySelector('button.cta');

/** Collect the filled-in answers as readable "Question: answer" lines. */
function collect() {
  const data = new FormData(form);
  const lines = [];
  for (const key of new Set([...data.keys()])) {
    const values = data.getAll(key).map(v => String(v).trim()).filter(Boolean);
    if (values.length) lines.push(`${label(key)}: ${values.join(', ')}`);
  }
  return lines;
}

/** Fall back to the visitor's own mail client. */
function handOffToMail(body, why) {
  const url = `mailto:${FEEDBACK_TO}?subject=${encodeURIComponent('Bede feedback')}&body=${encodeURIComponent(body)}`;
  if (url.length > MAILTO_SAFE_LENGTH) {
    note.textContent = why
      ? `We could not reach the server, and this is too long to hand to your email program. Please write to ${FEEDBACK_TO} — we read those the same.`
      : `That is longer than an email link can carry reliably. Shorten the longer answers, or write straight to ${FEEDBACK_TO}.`;
    return;
  }
  // Recorded before handing off so the assembled message can be
  // inspected — in a browser console, or by an automated check — rather
  // than only being visible once a mail client has already opened it.
  form.dataset.mailto = url;
  if (why) note.textContent = why;
  window.location.href = url;
}

/**
 * Submit through the demo API's Resend pipeline. Three calls, all of
 * which the public demo already makes: mint an anonymous code, exchange
 * it for a demo_code token, post the feedback. Throws on any failure so
 * the caller can fall back to mail rather than losing what was typed.
 */
async function sendViaApi(message) {
  const base = API_BASE.replace(/\/+$/, '');
  const codeRes = await fetch(`${base}/auth/demo-code`, { method: 'POST' });
  if (!codeRes.ok) throw new Error('demo-code ' + codeRes.status);
  const { code } = await codeRes.json();

  const loginRes = await fetch(`${base}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'demo_code', credential: code }),
  });
  if (!loginRes.ok) throw new Error('login ' + loginRes.status);
  const { token } = await loginRes.json();

  const email = String(new FormData(form).get('email') || '').trim();
  const res = await fetch(`${base}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      category: 'cx',
      // The endpoint caps message at 2000 characters; trim here so a
      // long answer is shortened visibly rather than 422'd on arrival.
      message: message.slice(0, 2000),
      ...(email ? { contact_email: email } : {}),
    }),
  });
  if (!res.ok) throw new Error('feedback ' + res.status);
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const lines = collect();
  if (!lines.length) {
    note.textContent = 'Nothing filled in yet — answer at least one question and try again.';
    return;
  }
  // Marked so it is obvious in the inbox that this came from the website
  // rather than from inside a session, since both land in the same place.
  const body = '[Website feedback form]\n\n' + lines.join('\n\n') + '\n';

  if (!API_BASE) { handOffToMail(body); return; }

  button.disabled = true;
  const original = button.textContent;
  button.textContent = 'Sending…';
  note.textContent = 'Sending — this can take a moment if the server has been idle.';
  try {
    await sendViaApi(body);
    form.hidden = true;
    note.textContent = 'Thank you — that reached us. If you left an email we will reply to it.';
  } catch (err) {
    button.disabled = false;
    button.textContent = original;
    handOffToMail(body, 'We could not reach the server just now, so we have opened your email program with your answers instead — nothing you typed is lost.');
  }
});
