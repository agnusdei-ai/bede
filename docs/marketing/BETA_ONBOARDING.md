# Public demo beta and onboarding

The public demo beta ends December 31, 2026. This is not a public launch
date or an extension of a family's separate 30-day offer.

Onboarding requests are open now through `/inquire/` and email to
`info@agnusdei.ai`. Home, homeschool, FAQ, inquiry, and demo launch pages
provide these paths. Existing form validation, recipient routing, consent,
and delivery behavior are unchanged; submitting a request is not enrollment.

The demo entry notice, launch metadata and FAQ, public site, and current
marketing handout footers share the same beta date. The copy tests in
`demo/src/betaOnboardingCopy.test.ts` guard the date and contact paths.
This update changes the announcement, not runtime expiry or trial licensing.

The demo build uses Vite 6.4.6, the compatible patched release. Vite 6.4.5
was blocked by the package firewall; Vite 8 is outside the existing React
plugin's supported peer range. No firewall settings are changed.
