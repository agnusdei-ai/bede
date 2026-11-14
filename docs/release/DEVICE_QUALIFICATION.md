# Device and browser qualification for a release candidate

**What this is.** The checklist for qualifying Bede's web client on iPhone,
iPad, Android, Windows, macOS and Linux for one exact release candidate. It is
a record to fill in, not a claim that any row has passed. Every row starts as
**NOT RUN**, and NOT RUN is never a pass.

Coverage comes from three separate layers, and none stands in for another:

1. **Automated browser coverage in CI**: `.github/workflows/cross-platform-browser-journeys.yml`.
2. **Physical devices against the real deployment**: the rows below, done by a person.
3. **Native packaging**: each installed app is its own release target (see "Release targets").

A green desktop browser run says nothing about a phone, and a passing
emulated phone says nothing about a physical one.

## 1. Automated layer (CI)

Dispatch the workflow with the candidate's full 40-character SHA. It checks
out that exact commit and refuses to run if HEAD differs. Pull requests that
change the app UI, its dependencies, or the API routes and middleware the
journeys drive also run it.

| Runner | Profile | Browsers | What a pass shows |
|---|---|---|---|
| `windows-2022` | desktop | Google Chrome, Microsoft Edge, Playwright Firefox | The journeys complete in those browsers on Windows |
| `macos-15` | desktop | Google Chrome, Microsoft Edge, Playwright WebKit, Playwright Firefox | The same on macOS. WebKit is the Safari engine, **not Safari** |
| `ubuntu-24.04` | desktop | Google Chrome, Playwright Firefox | The same on Ubuntu 24.04 |
| `ubuntu-24.04` | boundary | Google Chrome, Playwright Firefox, Playwright WebKit | The boundaries in section 1a hold in those engines |
| `macos-15` | mobile (**emulated**) | iPhone 15 and iPad Pro 11 on WebKit, Pixel 7 on Chromium; each portrait and landscape | The layout and core journeys work at those viewports with touch and a mobile user agent. **Not** evidence about a physical device |

"Playwright Firefox" and "Playwright WebKit" are the engine builds Playwright
ships, not the branded browsers. Results say which was used.

Every runner uses one local service: the real API on file-backed SQLite and a
loopback model stub. That is **not** the production server shape (section 3).

**Fail-closed.** The run fails if any expected check is missing, not only if
one fails, and if `results.json` was never written. Each run records the OS
image, the Playwright version and every browser's exact version in its
`results.json`. Candidate (dispatched) evidence is kept 90 days; download it
into the release record before then.

## 1a. Boundaries checked on every run of the `boundary` row

Each is a failure class this codebase has already got wrong or guards on
purpose. The row runs on its own service, because the last check locks the
parent account.

| Boundary | Required outcome |
|---|---|
| Open redirect after login | A `returnTo` of `https://…`, `//…`, `/\…` or `javascript:` lands inside the app (`utils/safeRedirect.ts`) |
| Wrong password | A plain error, still on the login page, no token, and never "your session ended" |
| A token the server rejects | Logged out with "Your session ended", not silently (`utils/logoutNotice.ts`) |
| Back after logout | No learner from the household on screen, no token |
| Upload over 25 MB | Refused in the browser before anything is sent |
| Text named `.png` | Refused by the server on its real bytes (422), never read |
| Double-tapped Approve | Exactly one approved practice set |
| Blank message | Not sent |
| Message over 2,000 characters | Not sent; the words stay in the box; the child is told it is too long, never that the connection failed |
| A child on parent pages | `/pod/configs` and a sibling's practice refused; no parent content or sibling on screen |
| Text at 175% on a phone-width screen | No sideways page scroll |
| Repeated wrong passwords | The parent is locked even with the right password, and account recovery still answers |

The over-long message row found a real defect: the chat sent the message, the
server refused it, and the child was told "we lost the connection". The chat
now keeps the words and says the message is too long
(`SocraticChat.messageLength.test.tsx`).

## 2. Physical layer: the support matrix

Record exact versions when you test. Do not promise "all iOS", "all Android"
or "all Linux"; support the current stable versions plus any older version
the pilot's device inventory actually needs.

| Platform | Physical acceptance | Result |
|---|---|---|
| iPhone | Safari on a real iPhone; installed web app separately if offered | NOT RUN |
| iPad | Safari on a real iPad, portrait and landscape | NOT RUN |
| Android | Chrome on a real Android phone; a tablet only if tablets are in scope | NOT RUN |
| Windows | A Windows client against the pilot server; Windows Hello or a security key if supported | NOT RUN |
| macOS | Real Safari; Touch ID or a security key (`scripts/qualification/mac_check.py --browser safari`); printing and uploads | NOT RUN |
| Linux: Ubuntu 24.04 LTS | Chrome and Firefox on a desktop install; microphone, downloads and printing | NOT RUN |
| Linux: Debian 12 | Chrome and Firefox on a desktop install; microphone, downloads and printing | NOT RUN |

### The journeys every row runs

| Journey | Required outcome |
|---|---|
| Open and authenticate | Trusted HTTPS; the right role; no broken redirect or login loop |
| Select a learner | The right record; same-name learners stay distinguishable; no content left from a previous user |
| Review evidence | Source information and teacher choices stay visible and usable |
| Approve, edit, reject | The state persists after reload; a double tap does not create a duplicate action |
| Tutoring | Streaming completes or reports a failure plainly; an interrupted connection recovers safely |
| Voice | Permission granted and denied, recording, playback and interruption all behave |
| Upload | Camera and file selection, supported formats, size limits and rejection messages work |
| Paper workflow | The PDF opens or downloads, the answer key is right, and it prints without clipping |
| Session lifecycle | Logout, expiry, revocation, background and resume, and reconnect expose nothing unauthorized |
| Usability | Touch, keyboard, scrolling, zoom, orientation, English and Spanish all remain usable |

Use sample learners only.

### Only a physical device can show these

Automation covers interface logic and injected media fixtures. These need a
person on a real device:

- passkey enrollment and sign-in;
- microphone permission, audio routing and interruptions (a call, another app);
- the camera and the file picker;
- sharing and actually printing a PDF;
- launching from the home screen, and background and resume;
- trusting the campus server's certificate and reaching it over the network.

Playwright's Android automation is experimental, so physical Chrome on
Android is the Android gate.

### HEIC

Either decode a real HEIC photo with the shipped runtime, if the mobile
upload advertises HEIC, or exclude HEIC and confirm the upload is refused
with a clear message rather than failing silently. Today the HEIC decoder
fails closed unless libheif is at least 1.23.7, and its tests skip.

| HEIC decision | Result |
|---|---|
| Decoded on the shipped runtime, or excluded with a verified clear refusal | NOT RUN |

## 3. One production-shaped session

The per-runner SQLite services above cannot show this. For the pilot, run one
session with:

> the exact candidate backend and frontend, the real pilot configuration, a
> non-superuser PostgreSQL, trusted HTTPS, and several client platforms using
> that one service at the same time.

1. Install the exact Mac candidate.
2. From each device, not only from the Mac, check the hostname, certificate
   trust and that the backend is reachable.
3. Connect the iPhone, iPad, Android, Windows, Mac and Linux clients in the
   matrix.
4. Run independent teacher sessions at the same time.
5. Exercise grant and revoke, cross-campus denial, restart and reconnect.
6. Confirm the expected provider and network behavior with sample inputs.

Never bypass TLS, CORS, MFA or authorization to make a client pass.

| Production-shaped session | Result |
|---|---|
| All supported clients against one candidate service | NOT RUN |

## 4. What a row must record

A row is complete only when it names all of these:

- the candidate source SHA, and the frontend and backend build identities;
- the artifact checksum, where there is an artifact;
- device, OS and browser versions;
- whether it was automated, emulated or physical;
- the tester, the time, the result and where the evidence is kept;
- any feature excluded for that row.

A row with an unresolved failure in a required journey has not passed. NOT
RUN and an unexpected skip are not passes. Any code change after a row is
recorded starts a new candidate and new evidence.

## 5. Release targets are separate

| Target | Qualified by |
|---|---|
| Web client | This document |
| Installed web app (PWA) | Install, standalone launch, cache and update behavior, logout and stale data |
| iOS and iPadOS native wrapper | **HOLD.** The bundled app runs from `capacitor://localhost` and cannot rely on the web app's same-origin API or HTTPS passkeys. See `IOS_IPADOS_RC1.md`. Screenshots or an Xcode build cannot close this |
| Mac server and installer | Install, prerequisites, trusted HTTPS, PostgreSQL, startup and recovery, artifact identity |
| Windows or Linux server | Only if such a server package is actually released. Supporting Windows or Linux as a browser client promises no server install |
