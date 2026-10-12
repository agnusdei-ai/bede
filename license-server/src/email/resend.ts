/**
 * Resend HTTP delivery — the email vendor the family instance already uses
 * (homeschool-api/services/email_service.py calls Resend's REST API), called
 * here over `fetch` with no SDK. Plain REST, JSON in / JSON out, and an
 * error that PROPAGATES: a failed delivery must be visible (the event is
 * already recorded; the operator API's resend action — later staged task —
 * re-delivers the stored key), never silently swallowed.
 */

import { TRIAL_DAYS } from "../license/issue";

const RESEND_URL = "https://api.resend.com/emails";

export interface ResendClient {
  send(input: { to: string; subject: string; html: string }): Promise<void>;
}

/** Escape for interpolation into HTML email bodies — customer emails are
 * data, and data never reaches HTML unescaped. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function licenseDeliveryEmail(input: {
  planName: string;
  licenseKey: string;
}): { subject: string; html: string } {
  // The literal string the family pastes: `LICENSE_KEY=` + the signed token —
  // the exact format docs/SELLING_BEDE.md and the setup wizard teach.
  const keyLine = `LICENSE_KEY=${input.licenseKey}`;
  return {
    subject: `Your Bede ${input.planName} license key`,
    html: [
      "<p>Welcome to Bede!</p>",
      `<p>Your ${escapeHtml(input.planName)} is active. To finish setting up your family's instance:</p>`,
      "<ol>",
      "<li>Start your Bede instance (<code>make setup</code>, per the setup guide).</li>",
      "<li>Open <strong>Parent Setup → License</strong> and paste the key below.</li>",
      "</ol>",
      "<p>License key (paste the whole line, including the <code>LICENSE_KEY=</code> prefix):</p>",
      `<p style=\"font-family: ui-monospace, monospace; font-size: 13px; word-break: break-all;\">${escapeHtml(keyLine)}</p>`,
      "<p>Keep this email — it is your only copy of the key. If you lose it, contact us and we can re-send it.</p>",
      "<p>— The Bede team</p>",
    ].join("\n"),
  };
}

/** The trial template — deliberately its own email (the spec's delivery
 * rule): it says TRIAL up front, carries the baked-in expiry date, and
 * points at the same paste-a-key setup. No billing language — no card was
 * ever taken. */
export function trialDeliveryEmail(input: { expiresDate: string; licenseKey: string }): {
  subject: string;
  html: string;
} {
  const keyLine = `LICENSE_KEY=${input.licenseKey}`;
  return {
    // `TRIAL_DAYS`, never a literal: a key is signed with the term in
    // force when it was minted, and a literal here would mislabel any key
    // signed under a different one.
    subject: `Your Bede ${TRIAL_DAYS}-day free trial`,
    html: [
      "<p>Welcome to Bede!</p>",
      // No card was taken, and that is stated as the fact it is. What is NOT
      // stated is the old blanket "nothing will auto-charge": register entry
      // 39 §2 forbids retaining it, because the trial now converts to a
      // recurring subscription once a family provides a card and authorizes
      // the charge. Saying "no card was taken" is true and narrow; saying
      // "nothing will ever auto-charge" is a promise about a flow that now
      // exists.
      `<p>Your <strong>${TRIAL_DAYS}-day free trial</strong> is active through <strong>${escapeHtml(input.expiresDate)}</strong>. No card was required to start it, and none is on file. When the trial ends, lessons stop until a licence is applied.</p>`,
      "<p>To finish setting up your family's instance:</p>",
      "<ol>",
      "<li>Start your Bede instance (<code>make setup</code>, per the setup guide).</li>",
      "<li>Open <strong>Parent Setup → License</strong> and paste the key below.</li>",
      "</ol>",
      "<p>Trial key (paste the whole line, including the <code>LICENSE_KEY=</code> prefix):</p>",
      `<p style=\"font-family: ui-monospace, monospace; font-size: 13px; word-break: break-all;\">${escapeHtml(keyLine)}</p>`,
      "<p>Ready to continue after the trial? The Annual Family Membership is $2,149/year for up to six children — one price, the whole household.</p>",
      "<p>— The Bede team</p>",
    ].join("\n"),
  };
}

/** The trial-ending reminder — the one notice sent between issuance and the
 * product stopping.
 *
 * Deliberately plain about the consequence. A reminder that says "upgrade now!"
 * and not "the app stops tutoring on this date" is a sales email pretending to
 * be a service one, and the family finds out the hard way. So it states the
 * date and what happens on it, because a family about to lose lessons is owed
 * both in plain words.
 *
 * `termDays` is the KEY's own term, passed in rather than read from
 * `TRIAL_DAYS`: a trial already running when decision 36 shortened the term
 * carries 30 days, and telling that family their "7-day trial" ends in three
 * weeks would be both wrong and confusing.
 *
 * **This is not decision 36’s §3 pre-card notice.** That one must state the plan,
 * the billing cadence, the exact recurring amount and currency, when the first
 * charge lands, and how to cancel before it — and three of those are
 * unresolved (decision 36). Writing a half-set of those disclosures into this
 * email would produce something a later reader mistakes for the real notice,
 * so this stays a trial-ending note and says only what is true today.
 */
export function trialEndingEmail(input: { expiresDate: string; daysLeft: number; termDays: number }): {
  subject: string;
  html: string;
} {
  const when =
    input.daysLeft <= 0
      ? "today"
      : input.daysLeft === 1
        ? "tomorrow"
        : `in ${input.daysLeft} days`;
  return {
    subject: `Your Bede trial ends ${when}`,
    html: [
      `<p>Your Bede ${input.termDays}-day free trial ends <strong>${escapeHtml(input.expiresDate)}</strong> (${escapeHtml(when)}).</p>`,
      "<p><strong>What happens then.</strong> Lessons stop. Bede will not tutor without a current license key — a parent can still sign in and apply one, and nothing on your machine is deleted. Your instance runs in your house, so your family's work stays where it is.</p>",
      // Narrow and true: no card is on file. Deliberately NOT the old
      // blanket "nothing will auto-charge", which decision 36 §2 forbids
      // retaining now that the trial converts.
      "<p><strong>No card is on file.</strong> None was taken when the trial started. Continuing means subscribing — you would be asked for a card and to authorize a recurring charge, and that authorization is yours to give.</p>",
      "<p>To continue, the Annual Family Membership is $2,149 USD per year for up to six children — one price for the whole household, recurring yearly until cancelled. Once you subscribe, the key arrives by email and you paste it into <strong>Parent Setup &rarr; License</strong>.</p>",
      "<p>If Bede is not right for your family, you need do nothing at all.</p>",
      "<p>&mdash; The Bede team</p>",
    ].join("\n"),
  };
}

export function createResendClient(apiKey: string, fromAddress: string): ResendClient {
  return {
    async send({ to, subject, html }: { to: string; subject: string; html: string }) {
      const response = await fetch(RESEND_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ from: fromAddress, to, subject, html }),
      });
      if (!response.ok) {
        // Never swallow: read the body for the operator's log, then throw.
        const detail = await response.text().catch(() => "");
        throw new Error(
          `Resend delivery failed (${response.status}): ${detail.slice(0, 500)}`,
        );
      }
    },
  };
}
