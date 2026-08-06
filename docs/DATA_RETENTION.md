# Data Retention & Deletion

This documents what Bede actually keeps, for how long, and how to delete
it — the technical retention policy referenced throughout `CLAUDE.md` and
`docs/PARENT_SETUP.md`. It is **not legal advice or a compliance
certification** (see the COPPA note at the bottom); it's a factual
description of the code's behavior so a parent, and anyone reviewing this
deployment for a family or organization, can see exactly what's retained
and how to remove it.

Two genuinely different situations are covered here — don't conflate them:

- **Your family's own self-hosted instance** (`docs/PRODUCTION_SETUP.md`)
  — you run the database yourself. There's no third party holding your
  child's data; retention here is about giving *you* a practical way to
  review and delete it, not about an operator's obligations to you.
- **The public demo** (`docs/DEMO_HOSTING.md`) — a cloud-hosted, shared
  instance visited by pseudonymous strangers. Retention here is genuinely
  about limiting how long the operator holds anyone's data.

## Your family's data (self-hosted instance)

Every table below is scoped to one student by `student_name` and is
**retained indefinitely until you delete that student** — there is no
automatic expiry, because a family may use the same student profile for
years and nothing here assumes otherwise.

| Table | What it holds |
|---|---|
| `student_configs` | The day's subject/grade/context plan |
| `voice_profiles` | The encrypted voice-biometric embedding |
| `narration_assessments` | Rubric scores from narration/discussion |
| `learner_profiles` | Bede's synthesized learner-type read (trivium stage, processing style, etc.) |
| `learner_behavior_checks` | The minimal kinesthetic/reading-writing/visual adaptation counter (see `CLAUDE.md`'s "processing_style adaptation" note for what this is and isn't) |
| `lesson_bookmarks` | One short, internal, Bede-authored resume-point note per subject — where that subject left off, for continuity into the next session (see `CLAUDE.md`'s "Lesson continuity (bookmarks)" note). Never shown in the app; not a tracked metric |
| `mastery_profiles` | The math skill-mastery vector (IRT/CDM/KST — see `docs/diagnostic/`) |
| `diagnostic_evidence_log` | Derived probe deltas (skill_id, prior→posterior, probe_id, model_used, timestamp — never a transcript or probe text) feeding both the vector above and the end-of-session Math Skill Growth report; on by default (`DIAGNOSTIC_EVIDENCE_LOG_ENABLED`) |
| `session_transcripts` | The full encrypted session transcript, for parent review |
| `api_usage_events` | Per-call token counts (student-scoped rows only — see below) |

**Deleting a student:** Pod Dashboard → each student's card → **Delete all
data…** → type the student's name to confirm. This calls
`DELETE /pod/configs/{student_name}`
(`homeschool-api/services/student_deletion.py`), which removes the
student's rows from **every table above in one action** — before this,
that endpoint only removed the day's config, and no page in the app ever
called it or the separate voice-deletion endpoint, so there was no
practical, in-app way to actually delete a child's data at all. This is
irreversible.

**Not touched by that deletion, on purpose:**
- `audit_logs` — a security record kept independent of any single student
  (login attempts, rate limiting, safeguarding alerts). Deleting a student
  doesn't rewrite the history of what happened on this deployment.
- `parent_security_keys` / `parent_totp_config` — the *parent's* own MFA
  enrollment, unrelated to any child; manage these from the Parent Setup
  page's security section (or `DELETE /mfa/webauthn/{id}` / `DELETE
  /mfa/totp`) instead.

**Backups:** deleting a student destroys the encryption key that their data
was stored under, not just the rows. Every copy of that child's data
becomes permanently unreadable at the same moment — including backups
already taken, and including by this deployment itself. The rows still
physically exist in an old `make db-backup` dump; nothing can open them.
That is what makes "irreversible" above literally true rather than a
statement about the live database only.

Two caveats, stated plainly because they are the difference between a
promise and a guarantee:

- **Data written before 2026-08-03 is not covered.** Rows created before
  per-student keys existed are encrypted under the deployment-wide key and
  stay readable in backups taken before then. They are upgraded
  individually the next time each one is written. If you have backups older
  than that date and this matters to you, prune them.
- **The audit log is deliberately excluded** (see below), so a deletion
  does not erase the security record of what happened on this deployment.

### One thing that is never in the database at all: the writing pad

Since the drawing canvas started keeping a child's page across a switch
back to the chat, there has been a piece of a child's work that outlives
the moment it was made, so it is worth saying exactly where it lives.

The page (the strokes, the paper style, the paper color) is held in the
browser's own `sessionStorage`, on the child's own tablet, under a key
scoped to that student. Nothing is sent to the API, nothing is written to
any table above, and there is nothing here for `DELETE
/pod/configs/{student}` to remove. The browser discards it when the tab
closes or the session ends; the child can discard it sooner with **New
page**, and the app itself discards it the moment a page grows past its
2 MB ceiling (telling the child first, so they can save it to the device
if they want to keep it). It is capped at one page per session on a
device, so a family tablet used by several children never accumulates
pages behind anyone's back.

A drawing the child deliberately **sends** to Bede is a different thing
and unchanged by any of this: it travels with that message and is retained
exactly as the rest of that conversation is.

## The public demo's data

The demo (`docs/DEMO_HOSTING.md`) is deliberately built to hold as little
as possible, and what little it holds expires automatically:

| Table | Retention | Mechanism |
|---|---|---|
| `demo_code_sessions` | ~6 hours | Opportunistic cleanup on every new code generation (`core/demo_code_session.py`) |
| `demo_code_unit_notes` | ~6 hours (same window as `demo_code_sessions`) | Opportunistic cleanup on every new code generation; also deleted immediately on explicit logout, same as its `demo_code_sessions` row. Holds only the optional "what are we already covering at home" note behind the demo's Continuing Mastery card (see `CLAUDE.md`'s "Continuing Mastery (demo)" section) — never the conversation itself. |
| `demo_code_activity_logs` | ~6 hours (same window as `demo_code_sessions`) | Opportunistic cleanup on every new code generation; also deleted immediately on explicit logout, same as its `demo_code_sessions` row. One encrypted blob per demo code holding that session's work ledger — which skill was worked, how much help it took, and what Bede noticed about the work. Derived and structural, in the same class as `demo_code_sessions.mastery_vector_enc`: never the child's words, never a transcript. Deliberately NOT `skill_activity_logs`, which is a real family's permanent per-student record — see `CLAUDE.md`'s "The work ledger in the public demo" section. |
| `diagnostic_preview_uses` | Rolling window, per (hashed) IP | Opportunistic cleanup on each quota check (`core/diagnostic_preview_quota.py`) |
| `demo_interaction_signals` | 30 days | **Automatic** background purge, every 6 hours, for the life of the process (`main.py`'s `_periodic_data_purge`, calling `services/interaction_signals.purge_old_signals()`) |

The interaction-signals purge used to run only when a human manually
executed `scripts/export_interaction_signals.py` — it's now scheduled
automatically so the 30-day retention promise in that module's own
docstring and the demo's consent copy (`demo/src/App.tsx`) actually holds
without anyone remembering to run a script.

The demo never persists a transcript, a narration, or a learner profile at
all (`db=None` for demo-role sessions throughout the backend) — there's
nothing beyond the three tables above to delete.

## Not a compliance certification

This describes what the code does. Whether that satisfies COPPA, GDPR, or
any other regulation for your specific use of this deployment is a legal
question, not a code question — this document (and the tools it
describes) are meant to make an honest, informed legal review *possible*,
not to substitute for one. If you operate this for other families (a
co-op/parish `coop`-tier license, say), get your own legal review before
relying on anything here as a compliance statement.


## The work ledger (`skill_activity_log`)

One row per completed learning activity — what a student actually finished,
in which skill, on which date, and how much help it took. Holds no
transcript, no child's words, and no task prose: `detail_enc` is
`encrypt_json({skill_id, label, assistance, subject_area})`, the same
derived-not-raw privacy class as narration assessments and the diagnostic
evidence log.

Deliberately *not* a psychometric record. The mastery tables hold an
inference about the child; this holds an observation of an event. It is
parent-facing only, is never shown to a child, and is removed in full by
the cascading student deletion (`services/student_deletion.py`) like every
other per-student table.
