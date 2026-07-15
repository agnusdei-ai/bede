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
| `mastery_profiles` | The math skill-mastery vector (IRT/CDM/KST — see `docs/diagnostic/`) |
| `diagnostic_evidence_log` | Derived probe deltas feeding the vector above (off by default — `DIAGNOSTIC_EVIDENCE_LOG_ENABLED`) |
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

**Backups:** if you run `make db-backup` regularly (recommended in
`docs/PRODUCTION_SETUP.md`), deleting a student here does not retroactively
scrub them from backups already taken. Prune or re-take backups
separately if that matters to you.

## The public demo's data

The demo (`docs/DEMO_HOSTING.md`) is deliberately built to hold as little
as possible, and what little it holds expires automatically:

| Table | Retention | Mechanism |
|---|---|---|
| `demo_code_sessions` | ~6 hours | Opportunistic cleanup on every new code generation (`core/demo_code_session.py`) |
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
