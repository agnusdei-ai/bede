// Where the site's forms post, filled in at BUILD time — not by hand.
//
// This committed copy is deliberately empty. `scripts/build_pages_site.sh`
// overwrites it in the assembled publish/ directory using the same
// VITE_DEMO_API_BASE the demo build already consumes (demo/src/api.ts), so
// the API's URL is configured once, on the Worker, and neither this repo
// nor a person editing a file has to hold a copy of it.
//
// Empty is a working state, not a broken one: feedback-form.js falls back
// to handing the visitor's answers to their own mail client (or, for a
// long survey, back to them to copy), so a local preview and a build with
// no variable set both still work.
//
// Loaded as its own file rather than an inline <script> so the site's CSP
// (site/_headers) can keep script-src 'self' with no 'unsafe-inline'.
window.BEDE_API_BASE = '';
