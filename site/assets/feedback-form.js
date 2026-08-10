// ── The one form script for every form page on this site ──────────────
// Used by /feedback/ (tell us what to fix), /survey/ (the beta parent
// survey) and /educators/ (the co-op educator survey). Each page
// configures itself through data- attributes on its own <form>; there is
// no per-page copy of this file and no per-page question list in here.
//
//   data-category     the API's FeedbackRequest.category, which is what
//                     decides the subject-line prefix on the email that
//                     arrives (see homeschool-api/services/email_service.py's
//                     _feedback_prefix). 'cx' or 'beta_survey'.
//   data-tag          a short marker put at the top of the message body so
//                     it is obvious in the inbox which page it came from,
//                     since all of them land in the same place.
//   data-mail-subject the subject line used only by the mailto fallback
//                     below, where there is no API to set one.
//
// Question text is read from each page's own markup — a <fieldset>'s
// <legend>, or the <label for=...> of a plain field — rather than from a
// map in here. That is deliberate: a map would be a second copy of every
// question, and the failure mode of the two disagreeing is an answer
// arriving in the inbox filed under a question that is no longer on the
// page. See docs/BETA_SURVEY.md's "Keeping the three channels honest".
//
// ── Where this form sends ─────────────────────────────────────────────
// Preferred path: the demo API's own POST /feedback, which already
// routes to the operator's inbox through Resend. That endpoint needs a
// token, but the demo's anonymous entry (POST /auth/demo-code) is public
// by design, so a website visitor can get one the same way a demo
// visitor does — mint a code, exchange it for a demo_code JWT, submit.
// agnusdei.ai and www.agnusdei.ai (and the .io fallback domain) are all
// already in the API's CORS_ORIGINS (render.yaml), so no backend change is
// required for this to work.
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
// If you DO set this, two other things have to move with it. Add that
// Render origin to site/_headers' connect-src, and correct
// site/privacy/index.html, which currently states that the static pages
// "contact nothing but your own browser" — true only while this is ''.
// That page promises a complete, code-audited inventory, so turning this
// on without amending it makes a public privacy claim false.
// On the CSP: the site's Content-Security-Policy only
// allows 'self' by default, and a CSP-blocked fetch here still degrades
// gracefully to the mailto fallback (the catch block below), but the
// visitor's answers would go out by email every time instead of the
// faster in-app path you just turned on.
//
// Lives in its own file (not an inline <script>) so the site's CSP
// (site/_headers) can set script-src 'self' with no 'unsafe-inline'
// exception.
const API_BASE = '';
const FEEDBACK_TO = 'info@agnusdei.ai';
// mailto URLs get truncated by some mail clients past roughly 2000
// characters, which would silently eat the end of a long answer. Warn
// rather than let that happen quietly.
const MAILTO_SAFE_LENGTH = 1900;

const form = document.querySelector('form[data-category]') || document.getElementById('feedback-form');
const note = document.getElementById('form-note');

const CATEGORY = form.dataset.category || 'cx';
const TAG = form.dataset.tag || '[Website form]';
const MAIL_SUBJECT = form.dataset.mailSubject || 'Bede feedback';

const button = form.querySelector('button.cta');

/**
 * The question a control belongs to, taken from the page itself.
 * A grouped control (radio, checkbox) is described by its fieldset's
 * legend; a plain input or textarea by its own <label for>. Falls back to
 * the field name so an unlabelled control still reports something rather
 * than being dropped.
 */
function questionFor(el) {
  const fieldset = el.closest('fieldset');
  if (fieldset) {
    const legend = fieldset.querySelector('legend');
    if (legend) return legend.textContent.trim();
  }
  if (el.id) {
    const escaped = window.CSS && CSS.escape ? CSS.escape(el.id) : el.id;
    const labelled = form.querySelector(`label[for="${escaped}"]`);
    if (labelled) return labelled.textContent.trim();
  }
  const wrapping = el.closest('label');
  if (wrapping) return wrapping.textContent.trim();
  return el.name;
}

/**
 * Collect the filled-in answers as readable "Question: answer" lines, in
 * the order the questions appear on the page.
 */
function collect() {
  const data = new FormData(form);
  const lines = [];
  const seen = new Set();
  for (const el of form.elements) {
    if (!el.name || seen.has(el.name)) continue;
    seen.add(el.name);
    const values = data.getAll(el.name).map((v) => String(v).trim()).filter(Boolean);
    if (values.length) lines.push(`${questionFor(el)}: ${values.join(', ')}`);
  }
  return lines;
}

/**
 * Too long for a mailto link. Do NOT just say so: these pages promise
 * "nothing you typed is lost", and telling someone who has just answered
 * twenty-five questions to "shorten the longer answers" breaks that
 * promise at the worst possible moment.
 *
 * A fully-answered survey exceeds MAILTO_SAFE_LENGTH easily — the limit
 * was sized for the twelve-field feedback form and these are twice that —
 * so this is an ordinary outcome here, not an edge case. Hand the visitor
 * the assembled text instead, ready to copy, so the work survives even
 * though the link cannot carry it.
 */
function handOffToClipboard(body, why) {
  note.textContent = why
    ? `${why} Your answers are below, ready to copy — please paste them into an email to ${FEEDBACK_TO} and we will read them the same.`
    : `You answered enough that this is too long for an email link to carry. Nothing is lost: your answers are below, ready to copy. Paste them into an email to ${FEEDBACK_TO}.`;

  if (form.querySelector('#form-overflow')) return;

  const wrap = document.createElement('div');
  wrap.className = 'field';
  wrap.id = 'form-overflow';

  const area = document.createElement('textarea');
  area.readOnly = true;
  area.rows = 8;
  area.value = body;

  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'cta';
  copy.textContent = 'Copy my answers';
  copy.addEventListener('click', async () => {
    area.select();
    try {
      // Not available on an insecure origin or in some older browsers, so
      // the selection above is the real fallback: the text is already
      // highlighted and one keystroke away either way.
      await navigator.clipboard.writeText(body);
      copy.textContent = 'Copied — now paste it into an email';
    } catch {
      copy.textContent = 'Selected — press Ctrl+C (or Cmd+C) to copy';
    }
  });

  const mail = document.createElement('a');
  mail.className = 'cta gilt';
  mail.href = `mailto:${FEEDBACK_TO}?subject=${encodeURIComponent(MAIL_SUBJECT)}`;
  mail.textContent = `Open an email to ${FEEDBACK_TO}`;

  wrap.append(area, copy, mail);
  form.append(wrap);
  // Guarded rather than assumed: this is the last statement in the one
  // path that exists to stop a visitor losing their answers, and it must
  // not be able to throw its way out of having appended them.
  if (typeof area.scrollIntoView === 'function') area.scrollIntoView({ block: 'nearest' });
}

/** Fall back to the visitor's own mail client. */
function handOffToMail(body, why) {
  const url = `mailto:${FEEDBACK_TO}?subject=${encodeURIComponent(MAIL_SUBJECT)}&body=${encodeURIComponent(body)}`;
  if (url.length > MAILTO_SAFE_LENGTH) {
    handOffToClipboard(body, why ? 'We could not reach the server just now.' : '');
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
      category: CATEGORY,
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
  // Marked so it is obvious in the inbox which page this came from, since
  // every form on this site lands in the same inbox.
  const body = TAG + '\n\n' + lines.join('\n\n') + '\n';

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
