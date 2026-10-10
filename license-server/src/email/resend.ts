/**
 * Resend HTTP delivery — the email vendor the family instance already uses
 * (homeschool-api/services/email_service.py calls Resend's REST API), called
 * here over `fetch` with no SDK. Plain REST, JSON in / JSON out, and an
 * error that PROPAGATES: a failed delivery must be visible (the event is
 * already recorded; the operator API's resend action — later staged task —
 * re-delivers the stored key), never silently swallowed.
 */

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
    subject: "Your Bede 30-day free trial",
    html: [
      "<p>Welcome to Bede!</p>",
      `<p>Your <strong>30-day free trial</strong> is active through <strong>${escapeHtml(input.expiresDate)}</strong>. No card was required and nothing will auto-charge — when the trial ends, the app asks for a license key.</p>`,
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
