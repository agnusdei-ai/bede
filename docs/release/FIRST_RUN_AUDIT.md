# First-run audit: install to first lesson to voice

A bounded audit of the path a family walks the first time: install, adult
sign-in, learner setup, first lesson, voice, then restart and recovery. Three
kinds of evidence are kept apart on purpose. A row never borrows confidence
from a column it was not checked in.

- **Code/test**: read in the code and pinned by a test in this repository.
- **Hosted browser**: driven in headless Chromium against the dev server with
  stubbed API responses. This is not a real deployment.
- **Owner-only**: needs the physical pilot Mac or a real service. Not done here.

No model was downloaded, no paid call made, nothing deployed.

## Findings

| # | Severity | Finding | State |
|---|----------|---------|-------|
| 1 | High | Re-running `setup.sh` or the wizard generated new `SECRET_KEY`, `MASTER_SECRET` and `POSTGRES_PASSWORD`. A new `MASTER_SECRET` makes the existing encrypted records unreadable and a new database password is refused by the existing volume. | Fixed in this change (both installers keep them). |
| 2 | High | `setup.sh` ended with "Bede is running!" even when the health check never passed. | Fixed: the banner says "installed but not answering yet" with `make status`/`make logs`. |
| 3 | Medium | Both installers asked for an OpenAI key only when OpenAI was the tutoring choice, so a Claude, Mistral or local family got text-only lessons with no prompt and no explanation. | Fixed: optional voice question, key reused when OpenAI already supplies it, skip allowed with its consequence stated. |
| 4 | Medium | The overwrite question read like a wipe ("start fresh") although data is kept. | Reworded: "Replace your settings?" with what is kept. |
| 5 | Low | A re-run dropped settings the installer does not manage (mail key, sandbox PIN, custom port); only a backup kept them. | Fixed: both installers carry them over; a setting answered again this run wins. |
| 6 | Open | After install there is no in-app place to add or replace a connection; it means editing `.env`. Guided in-app management is the intended destination. | Design only: `docs/design/CONNECTIONS_AND_READINESS.md`. Nothing built. |
| 8 | Fixed | The browser wizard showed a second key field for the voice even when OpenAI tutoring already supplied the key. | The field is hidden for the OpenAI choice and ignored by the server. |
| 7 | Open, on #875 | Under school (COPPA) enforcement `/tutor/voice` can report cloud speech as configured and available while synthesis is refused, and the cloud status copy states readiness before any test. | Reported to the owner; #875 is held and unchanged here. |

## Matrix

| Step | Code/test | Hosted browser | Owner-only |
|------|-----------|----------------|------------|
| Installer asks the right questions, writes `.env` | `test_installer_feature_choices.py`, `test_installer_consent.py`, `test_install_ack_end_to_end.py`, `scripts/setup_wizard/test_wizard.py` (real `setup.sh` with stubbed docker/curl; real wizard over HTTP) | Not applicable | Run on the Mac |
| Voice key: reuse, skip, speech-off kept, adapter order untouched | The same suites (new cases, each guard verified by breaking it) | Not applicable | Hear it speak |
| Re-run keeps data readable | New cases in both installer suites | Not applicable | Re-run on a Mac with real data |
| Stack actually boots after install | Not provable here (no Docker daemon) | No | Yes |
| Adult sign-in, learner setup | `docs/release/K12_JOURNEY_MATRIX.md` | Same document (sample data) | Yes |
| First lesson | Same | Same | Yes |
| Voice works | `tests/test_local_voice.py` and the voice routes (stubbed) | No audio | Yes: needs a real key and ears |
| Restart/recovery | `restart: unless-stopped`, daily licence refresh (CLAUDE.md) | No | Yes |

## Not verified here

A real Docker boot, any real speech call, the native Windows/Unix installer
scripts (they hand off to the wizard; their own prompts were not run), and every
physical-Mac check. Internal record only: the installer tells the customer
"Bede's voice is connected" when a key is entered; no speech call was made to
check the key, because paid verification calls are not authorized. A refused
key or a policy block is reported to the customer by the voice status notice,
with the actual problem. Closing this gap (a bounded, owner-approved check at
the first lesson) is a follow-up, not a copy change.
