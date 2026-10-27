# Bede guided introduction

The homepage's secondary action opens `/bede/tour/`. The public demo remains at
`/bede/`; the original YouTube link and inquiry links are unchanged.

The introduction places the 95-second overview beside its short instructions on
desktop and below them on phones. The transcript is collapsed by default.
The narrator is an explicitly fictional AI mother-and-educator persona, not a
testimonial or Bede's tutor voice. Both adult walkthroughs use scripted examples.

## Build and checks

`bash scripts/build_pages_site.sh` builds the existing demo and the tour with
the demo's existing, locked React/Vite dependencies; no new packages are required.
The tour has its own entry, static assets and stylesheet, and does not call the API.

`node --test scripts/bede-tour-release.test.mjs` checks release wiring, media,
captions and the essential audience/disclosure constraints. It also runs as part
of `demo`'s test command. Native playback, seeking, captions and responsive layout
need browser verification as well.

Only the compact web-ready MP4/WebM renditions (each below 3 MB) are checked in
because the owner requested the video accompany the source. Raw narration,
capture frames and intermediate renders are not repository assets. This keeps
fresh-checkout playback independent of a separate media backend.

## Release boundary

The active deployment integration is **Workers Builds: bede**, despite the
legacy `build_pages_site.sh` filename. Do not assume Pages-specific deployment
skip flags control this Worker.

The source and delivery media can be prepared as a GitHub commit without
updating a remote branch. The owner must initiate branch creation, review and
the final publishing merge. Those actions can trigger Cloudflare builds.
A prepared commit is not evidence of a successful production deployment.
