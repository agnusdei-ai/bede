/**
 * License delivery email — the Worker-side counterpart to
 * homeschool-api/services/email_service.py's send_email(). Same Resend
 * HTTP API, same "escape everything, never trust caller-supplied HTML"
 * discipline.
 */
import type { LicensePayload } from './licensing';

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const TIER_LABELS: Record<string, string> = {
  trial: 'Trial',
  core: 'Core',
  coop: 'Co-op',
};

export function buildLicenseEmailHtml(licenseKey: string, payload: LicensePayload): string {
  const safeName = escapeHtml(payload.licensee);
  const tierLabel = TIER_LABELS[payload.tier] ?? payload.tier;
  const expiryLine = payload.expires
    ? `<p style="margin: 0 0 16px 0;">This trial runs through <strong>${escapeHtml(payload.expires)}</strong>.</p>`
    : '';
  return `\
<!DOCTYPE html>
<html>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2d3142; max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; margin: 0 0 4px 0;">Your Bede license</h1>
  <p style="font-size: 13px; color: #6b7280; margin: 0 0 24px 0;">
    ${tierLabel} license for ${safeName} — ${payload.seats} student seat${payload.seats === 1 ? '' : 's'}.
  </p>
  ${expiryLine}
  <p style="margin: 0 0 8px 0;">Paste this into your <code>.env</code> file as-is:</p>
  <div style="font-family: 'SF Mono', Menlo, monospace; font-size: 12px; word-break: break-all; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; line-height: 1.6;">
    LICENSE_KEY=${escapeHtml(licenseKey)}
  </div>
  <p style="font-size: 14px; line-height: 1.6; margin-top: 24px;">
    Both setup wizards (terminal and browser) will also prompt for this directly —
    see <code>docs/PRODUCTION_SETUP.md#licensing</code> in the Bede repo.
  </p>
  <p style="font-size: 12px; color: #9ca3af; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px;">
    This license is verified entirely offline by your own Bede server — nothing about
    your deployment is ever reported back to us.
  </p>
</body>
</html>`;
}

export async function sendLicenseEmail(
  resendApiKey: string,
  fromAddress: string,
  toAddress: string,
  licenseKey: string,
  payload: LicensePayload,
): Promise<boolean> {
  try {
    const resp = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${resendApiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: fromAddress,
        to: [toAddress],
        subject: 'Your Bede license',
        html: buildLicenseEmailHtml(licenseKey, payload),
      }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}
