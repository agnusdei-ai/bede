# Website demo discovery and unified survey

The public demo is served at `/bede/` by the existing combined site build
(`scripts/build_pages_site.sh`). Every marketing header and footer links there.
The homepage and homeschool hero use a direct **Launch Bede demo** action, not
an email inquiry. The demo still obtains a temporary access code and keeps its
existing consent, authentication, and backend availability requirements.

`/survey/` is the one website survey for parents, educators, co-op leaders, and
school teams. Other pages link to it rather than publishing separate forms.
The in-app beta survey is unchanged.

## Flow

1. Setting: required audience selection.
2. Experience: required usage selection and an optional short impression.
3. Needs: optional workflow or feature request.
4. Review: optional name/reply email and required permission to send.

`site/assets/survey-flow.js` progressively enhances the full HTML form, validates
each step, preserves answers when going back, and renders review text using DOM
text nodes. It makes no network requests and uses no browser storage.
`survey-flow.css` supplies the accessible form layout, controls, and focus states.

## Sending and fallback

`feedback-form.js` remains the single delivery implementation. With
`window.BEDE_API_BASE` set by `api-base.js`, it obtains anonymous demo access
through `/auth/demo-code` and `/auth/login`, then posts the complete response to
`/feedback` under `beta_survey`. The server emails its configured feedback inbox.
Only a successful response hides the form and confirms delivery.

Without the API, or when a request fails, the page opens an email draft and
explicitly says that the visitor still has to send it. Responses too long for
the API's 2,000-character message limit or a safe mailto URL are offered as
complete copyable text with an email link. Never truncate submitted answers.
No student records or attachments are requested. Contact details are optional.
The native form uses POST so a script failure cannot put answers in a URL.

## Verification

- `demo/src/websiteSurveyFlow.test.ts`: step validation, Back, safe review,
  permission gate, full API payload, no browser persistence, email fallback,
  and lossless oversized-response handoff.
- `homeschool-api/tests/test_beta_survey_category.py`: the hosted survey and
  in-app instrument use a category accepted by the API.
- `scripts/bede-production.test.mjs`: direct demo navigation, one survey only,
  asset completeness, no public checkout, and CSP-compatible scripts.
- `demo/src/contrastStyles.test.ts`: contrast/focus guardrails for marketing and demo.

Marketing plan rates remain email-only. No school affiliation or customer
agreement is implied. A successful local browser test with mocked delivery is
not proof that the live email provider delivered a message.
