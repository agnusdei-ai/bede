# Bede guided introduction

The homepage's primary “Watch Bede overview” action opens `/bede/tour/`.
Every shared header and footer also includes a concise “Bede overview” link.
The public demo remains at `/bede/`; the original YouTube link and inquiry links
are unchanged.

The introduction places the 103-second overview beside its short instructions on
desktop and below them on phones. The transcript is collapsed by default.
The overview uses one full-script recording, preserving its natural pauses.
There are no separately recorded passages, audio splices, or section-level
volume adjustments. Gentle full-track mastering balances the audio around
-16 LUFS with a -1.5 dBTP ceiling.

The same narrator and presentation are retained. The script includes Bede's
question about the Lion sparing the Mouse, followed by reasoning from the fable
and everyday application. The removed synthetic-narration line is absent from
the speech and on-page note. The narrator is a fictional delivery persona,
not a customer testimonial or Bede's tutor voice. Both adult walkthroughs use
scripted examples.

## Build and checks

`bash scripts/build_pages_site.sh` builds the existing demo and the tour with
the demo's existing, locked React/Vite dependencies; no new packages are required.
The tour has its own entry, static assets and stylesheet, and does not call the API.

`node --test scripts/bede-tour-release.test.mjs` checks release wiring, media,
captions and the essential audience/fictional-example constraints. It also runs as part
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

Remote branch updates and merges can trigger Cloudflare builds. Obtain the
owner's approval before making them; do not disable checks or deployment
controls. A merged commit is not evidence of a successful production deployment:
verify the corresponding Worker check before reporting it live.
