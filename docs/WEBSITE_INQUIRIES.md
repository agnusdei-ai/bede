# Self-service business inquiries

`/inquire/` is business intake, separate from the product survey at `/survey/`.
Families, co-ops, and charter schools choose their setting in one form.
Audience-specific entry links preselect that setting:

- `/inquire/?audience=homeschool`
- `/inquire/?audience=coop`
- `/inquire/?audience=charter_school`

The form collects contact name/email/role, estimated learners and grade bands,
deployment preference, requested help, timing, and optional location/context.
Co-ops and schools also provide organization, educators/staff, and sites;
co-ops provide estimated participating families. Estimates are explicitly
acceptable. No records, files, payment details, or enrollment are requested.

## Actual email delivery

The browser makes one JSON `POST /inquiries` to the API configured by the
existing build-time `VITE_DEMO_API_BASE` variable. The route does not mint a
demo code or depend on tutoring access, demo quotas, or a user account.

The server validates bounded fields and selects fixed owner inboxes:
homeschool goes to `bede@agnusdei.ai`; co-op and charter school go to
`info@agnusdei.ai`. There is no client-supplied recipient. This routing is
independent of the legacy `SALES_EMAIL` setting for the demo lead prompt.
The visitor's validated email becomes Reply-To, never From. The owner receives
a labeled engagement summary, with HTML escaped before rendering.

Delivery reuses `RESEND_API_KEY` and the verified `RESEND_FROM_ADDRESS`.
It requires the API backend to be deployed as well as the static site.
No new credentials or mail provider are needed. Never put credentials in
client JavaScript, logs, committed files, or the inquiry body.

The public route uses a separate three-per-minute, per-IP, per-process rate
limit in the existing middleware. A honeypot is also checked. This is basic
abuse protection, not a global/distributed bot-prevention guarantee.
Existing CORS and security middleware remain in place.

## Honest outcomes and privacy

Only a successful provider response produces `{"sent":true}`. This means
provider acceptance, not guaranteed final inbox delivery.
Missing provider configuration returns 503; a provider send failure returns
502; invalid inputs return 422. The UI requires an explicit `sent: true`
response, retains answers on failure, prevents concurrent duplicate clicks,
and times out requests after 20 seconds. A timed-out request may already
have reached the provider, so the UI warns before resending.

There is no automatic mailto fallback disguised as a submission. Direct
email links remain available as an explicitly separate manual option.
No inquiry database or browser storage is used; the resulting email remains
in the team's email system. Logs contain only audience and acceptance status,
not contact details, counts, organization names, or notes.

## Verification

Backend tests cover all audiences, fixed recipient selection, Reply-To,
HTML escaping, scope and consent validation, invalid-recipient rejection,
honeypot rejection, unavailable providers, and send failures. Middleware tests
exercise the three-per-minute budget. Frontend tests cover conditional fields,
preselection, clearing inactive fields, required selections, one direct POST,
duplicate-click protection, missing configuration, and truthful failure states.

Production validation still requires checking the deployed form/API versions
and a controlled email send authorized by the owner. Mocked tests do not prove
that an email reached either live inbox.
