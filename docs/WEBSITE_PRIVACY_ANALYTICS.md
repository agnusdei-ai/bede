# Website analytics disclosure

Owner-authorized correction of `/privacy/`, reviewed October 20, 2026.

## Verified observations

- Fresh-browser initial-load checks of `/`, `/research/`, `/inquire/`,
  `/survey/`, `/privacy/`, and `/bede/` each included a script from
  `static.cloudflareinsights.com` and attempted to request it. The demo also
  contacted its Render API.
- No cookies, localStorage entries, or sessionStorage entries were observed
  during those checks (two seconds after load). This is a bounded observation,
  not a statement about every region, later interaction, or hosting setting.
- No video was played, demo consent accepted, form submitted, lesson requested,
  or real email sent. Cookie and storage values were not printed.
- A deeper check distinguished inclusion from execution: the browser reported
  a Content Security Policy violation and a failed beacon request with reason
  `csp`. No RUM response was observed. The script's presence does not establish
  active collection or successful analytics delivery.
- The deployed notice omitted that injected script and described an email-only
  website where only the demo collected information, despite the inquiry and
  survey forms. The correction must not claim the blocked beacon is running.

## Provider evidence and scope

- [Cloudflare Web Analytics](https://www.cloudflare.com/web-analytics/)
  describes measurement without cookies, localStorage, or visitor fingerprinting.
- [Cloudflare's documentation](https://developers.cloudflare.com/web-analytics/about/)
  describes browser Performance API measurement, page views and visitors.
- The notice attributes the cookie-free description to Cloudflare rather than
  promising that every third-party service or hosting security feature is
  cookie-free. It identifies the included, currently blocked beacon separately
  from the demo's tutoring consent.
- Cloudflare account settings, retention configuration, and jurisdiction-specific
  legal compliance were not inspected or certified. No connected Cloudflare
  integration was available. Source review alone would not have detected the
  externally injected beacon.

## Changes

- Disclose the Cloudflare script on public pages and the hosted demo, the
  observed CSP block, the provider link, and the absence of a website analytics
  preference control. Do not loosen the security policy or enable analytics.
- Correct form and Resend disclosures; preserve audience routing, answer
  retention, storage-key inventory, and the existing AI-service disclosures.
- Remove absolute claims of no analytics, no outside scripts, collection only
  in the demo, and universal consent exemption. Shorten the video and
  server-versus-browser explanations without denying connection information
  reaches browser-contacted providers.
- No tracking configuration, provider settings, consent implementation, form
  transport, or new cookie banner is changed by this disclosure-only update.
- A privacy-scoped stylesheet wraps long domains and storage keys, including
  enlarged text on narrow screens; other website pages are unaffected.
- This does not establish that consent controls are unnecessary everywhere.
  [Current ICO guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/what-are-the-exceptions)
  distinguishes necessary storage and conditional statistical/appearance
  exceptions. Relevant visitor jurisdictions and the actual service setup
  still matter.

## Regression verification

Keep the storage inventory guards and add checks for the live-observed
  Cloudflare host, provider attribution, the observed CSP block and separation from tutoring consent,
forms, and removal of contradictory blanket claims. Browser-check the updated
page on mobile and desktop with light/dark device settings. Do not exercise
email submission or tutoring as part of this copy change.
