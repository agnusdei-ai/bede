# Vendor Data Flow

Which third parties Bede's code can send data to, what specifically goes
to each one, and whether it's required or opt-in. Companion to
`docs/sbom/` (the dependency bill of materials — this document is about
runtime data flow to external services, not library dependencies) and
`docs/SECURITY.md` (AIUC-1 vendor-due-diligence). Like the other docs in
this family, this is a factual description of what the code does, **not a
vendor risk assessment or a substitute for reviewing each vendor's own
terms, DPA, and subprocessor list yourself** before you decide whether
they're acceptable for your family or your deployment.

## Anthropic — required

**What's sent:** every tutoring turn's full context — the system prompt
(the digest-pinned constitution, Bede's persona/rules, the current
subject's guidance, the processing-style note, any parent-supplied
`lesson_focus`/`faith_emphasis`/`current_unit`), the conversation history
for the current subject, and the child's current message. If the child
used the handwriting canvas, that turn also includes the drawing as a
base64-encoded image. End-of-session summaries (`generate_session_summary`)
send the session's message history to produce the parent-facing report.

**Why it's required:** Anthropic's Claude models are Bede — there's no
tutoring without this call. `core/config.py` pins `tutor_model` (streaming,
`claude-sonnet-4-6`) and `session_model` (non-streaming,
`claude-haiku-4-5-20251001`, end-of-session summary only).

**What doesn't get sent:** raw encryption key material, other students'
data, voice biometric embeddings, or anything from the parent's own
account credentials — none of that is ever placed in a prompt. Credential-
shaped text a child or parent types is redacted before it reaches this
call (`_redact_credentials`, AIUC-1 A008 — see `docs/SECURITY.md`).

**Your own review:** see [Anthropic's Privacy Policy and Commercial Terms
of Service](https://www.anthropic.com/legal) for their retention and
training-use commitments for API traffic — this document describes what
Bede sends, not what Anthropic does with it afterward.

## OpenAI — optional, two independent features

Both are gated behind `OPENAI_API_KEY`; leaving it unset disables both,
and each is independently a real network call vs. a purely local one —
worth not conflating:

- **Text-to-speech (`services/voice_synthesis.py`), a real API call.**
  When configured, **Bede's own spoken lines** (not the child's messages)
  are sent to `https://api.openai.com/v1/audio/speech` (model
  `gpt-4o-mini-tts` by default, configurable voice/instructions) to
  synthesize the audio the child hears. Nothing the child said is ever
  part of this payload.
- **Voice enrollment transcription (`services/transcription.py`), NOT a
  network call.** Despite the name, this uses the open-source
  `openai-whisper` Python package running locally on your own server —
  no audio, and no data at all, leaves your machine for this feature.
  It shares a vendor name with the item above but not a data-flow path.

## Resend — optional, transactional email only

Gated behind `RESEND_API_KEY`. Four independent triggers, each sending an
address plus generated HTML to `https://api.resend.com/emails`
(`services/email_service.py`):

| Trigger | Recipient setting | Content |
|---|---|---|
| Post-session diagnostic notes | typed in by the parent at send time, never stored | Bede's end-of-session notes |
| Distress/danger safeguarding alert | `PARENT_EMAIL` | A short excerpt of what triggered it |
| Security anomaly alert (AIUC-1 E009) | `PARENT_EMAIL` | Event type, IP, occurrence count — no message content |
| Beta feedback | `FEEDBACK_EMAIL` (operator's own inbox) | Whatever the submitter wrote |

None of these addresses are ever written to the database or the audit log
(`services/email_service.py`'s module docstring) — each is used for
exactly the one outbound send that triggered it.

## Voice biometrics — never leaves your machine

Worth stating explicitly since it's easy to assume voice data is cloud
data: speaker verification (`services/voice_auth.py`, Resemblyzer + MFCC
similarity scoring) runs entirely locally. No enrollment audio, embedding,
or verification attempt is ever sent to any third party.

## Regenerating the SBOM

```bash
python3 scripts/generate_sbom.py
```

Regenerates both `docs/sbom/backend.cdx.json` and
`docs/sbom/frontend.cdx.json` (CycloneDX 1.5) from the currently committed
`requirements.txt`/`requirements-dev.txt` and `package-lock.json` — no
`pip install`/`npm install` required, so it works offline and doesn't
depend on matching Python/Node versions locally. Two caveats to know about
before treating either file as authoritative for an audit:

- **Backend versions are declared floors, not exact pins.**
  `requirements.txt` uses `>=` with no upper bound (see `docs/SECURITY.md`),
  so `backend.cdx.json` records the minimum version each dependency is
  allowed to resolve to, not necessarily what's actually running in any
  given deployment. Run `pip freeze` inside your own running container if
  you need exact installed versions.
- **Frontend versions are exact**, since `package-lock.json` pins real
  resolved versions — those entries are a genuine, accurate snapshot as of
  whenever the lockfile was last updated.
