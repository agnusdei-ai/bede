# Incident Response Plan

This documents what to actually do if something looks wrong on a Bede
deployment, or if you've found a security problem in Bede's code itself —
the accountability documentation referenced from `docs/SECURITY.md`. Like
that file and `docs/DATA_RETENTION.md`, this is a factual, practical guide
for this specific codebase, **not legal advice** — breach-notification
obligations vary by jurisdiction and by what data is involved; if you
suspect a real exposure, get real legal advice for your situation rather
than relying on anything below.

## Two different operators, two different plans

Same split `docs/DATA_RETENTION.md` draws, and it matters here too:

- **Your family's own self-hosted instance** (`docs/PRODUCTION_SETUP.md`) —
  you are the operator, the administrator, and the only "incident response
  team" there is. There's no separate company to call; the steps below are
  things you do yourself, on your own server.
- **The public demo** (`docs/DEMO_HOSTING.md`) — a real operator running a
  cloud-hosted, shared instance for pseudonymous strangers. Closer to a
  conventional incident-response situation: real (if pseudonymous) third
  parties, a real inbox to route reports to.

## Detection: what already tells you something's wrong

Bede doesn't wait for you to notice — several mechanisms already watch for
trouble and (where configured) email `PARENT_EMAIL`:

| Signal | Where it comes from | Real-time alert? |
|---|---|---|
| A child expresses distress/danger | `check_safeguarding()`, `AuditEvent.SAFEGUARDING` | Yes, if `PARENT_EMAIL` is set (`send_distress_alert`) |
| Repeated failed logins, JWT fingerprint mismatches, access-denied hits, or a blocked exfiltration attempt from one address | `core/audit.py`'s anomaly watch, `AuditEvent.ANOMALY_ALERT` — see `docs/SECURITY.md`'s E009 entry for exact thresholds | Yes, if `PARENT_EMAIL` is set (`send_security_alert`) |
| Rate limiting kicking in | `RateLimitMiddleware`, `AuditEvent.RATE_LIMITED` | No — audit log only |
| A blocked endpoint or response containing key material | `ExfiltrationGuard`, `AuditEvent.SUSPICIOUS_REQUEST` | Yes — this alone crosses the anomaly threshold on its own |

**Reading the full audit log today is API-only** — there's no dedicated
page in the parent UI yet (a real gap, tracked here rather than silently
assumed away). As a logged-in parent:

```bash
curl -H "Authorization: Bearer <your parent access_token>" \
  "https://<your-server>/api/admin/audit?limit=200"
```

Every entry is decrypted server-side and returned as plain JSON (`ts`,
`event`, `ip`, `ua`, `success`, `role`, `student`, `detail`) — see
`core/audit.py`'s `read_audit_log` for exactly which fields are ever
exposed this way (never raw key material).

## Severity

| Level | Examples | 
|---|---|
| **Critical** | Suspected compromise of `MASTER_SECRET` or the database's encrypted contents; a stranger has parent-level access to your instance |
| **High** | A safeguarding alert you can't immediately explain; a sustained anomaly-alert pattern (brute-force, probing) that doesn't stop on its own |
| **Medium** | An isolated anomaly alert with an obvious benign explanation (e.g., you mistyped your own password five times); a single rate-limit hit |
| **Low** | A one-off `SUSPICIOUS_REQUEST` you can attribute to a scanner/bot with no follow-through |

## Response — your family's self-hosted instance

1. **Identify.** Pull the audit log (above) around the time of the alert.
   Look for the same `ip`/pattern recurring, and whether it's plausibly you
   or your family (a forgotten device, a mistyped PIN) versus genuinely
   unfamiliar.
2. **Contain.**
   - Rotating `SECRET_KEY` in `.env` and running `make restart` immediately
     invalidates **every** issued JWT — every parent and child session gets
     logged out. Safe, reversible, no data loss. Do this first if you
     suspect a stolen session token.
   - Change `PARENT_PASSWORD`/`CHILD_PIN` in `.env` and `make restart` if
     you suspect either was guessed or observed.
   - **Do not rotate `MASTER_SECRET` as a containment step.**
     `core/encryption.py`'s docstring is explicit about this:  changing it
     makes **all** previously stored data permanently unreadable — every
     student config, voice profile, transcript, everything. Only ever do
     this if you're rebuilding from scratch anyway, never as a response to
     a suspected breach (it destroys the evidence and the data both).
3. **Eradicate.** `make update` to pull the latest code (in case the
   incident involved a since-patched vulnerability) and rebuild. If you
   suspect the host itself (not just Bede) is compromised, that's outside
   Bede's scope — treat it as you would any other compromised machine on
   your network.
4. **Recover.** `make status` to confirm the stack is healthy again;
   re-enable tablets/devices one at a time rather than all at once, so a
   repeat incident is easier to isolate.
5. **Review.** No formal postmortem process is expected for a one-family
   deployment, but it's worth a few minutes: what did the audit log show,
   what did you change, would you notice faster next time? `make db-backup`
   regularly (see `docs/PRODUCTION_SETUP.md`) so "restore to before this
   happened" is always an option.

**If the incident is a child-safety concern rather than a technical
one** — the safeguarding check did its job and stopped tutoring, or you're
worried about something a child said — this isn't a "redeploy and rotate
keys" situation. Follow up with your child directly and, if warranted,
appropriate real-world resources; nothing in this document substitutes for
that judgment call.

## Response — the public demo

If you operate `docs/DEMO_HOSTING.md`'s shared instance:

1. Reports usually arrive via `FEEDBACK_EMAIL` (`routers/feedback.py`) —
   the same inbox already configured for beta feedback, deliberately
   separate from any individual family's `PARENT_EMAIL`.
2. If you suspect the demo itself is being abused (credential stuffing
   against `DEMO_PIN`, scraping, cost abuse against your
   `ANTHROPIC_API_KEY`) — rotate `DEMO_PIN` and/or `ANTHROPIC_API_KEY`
   immediately; both are cheap, non-destructive rotations (unlike
   `MASTER_SECRET` above).
3. Taking the demo fully offline is a platform-level action (stop/remove
   the deployment per whatever hosting method `docs/DEMO_HOSTING.md`
   describes) — there's no in-app "pause" switch.
4. The demo's data model is pseudonymous by design (`docs/DATA_RETENTION.md`
   — short-lived demo codes, no account, no email required to use it),
   which limits what there is to actually expose. That's a design property,
   not a substitute for actually checking what happened.

## Breach notification

- **Self-hosted family instance:** there is no one else to notify — you
  are both the operator and the data subject's guardian. This section
  exists for completeness, not because a self-hosted single-family
  deployment has third-party notification obligations in the way a SaaS
  product would.
- **Public demo:** if you believe demo visitors' pseudonymous data was
  actually exposed, whether and how you're obligated to notify anyone
  depends on your jurisdiction and what was actually exposed — get real
  legal advice rather than treating this document as sufficient. What Bede
  itself can tell you: exactly what tables exist and what they hold is in
  `docs/DATA_RETENTION.md`; nothing here collects government ID, precise
  location, or payment information by design, which narrows (but doesn't
  eliminate) what there is to assess.

## Reporting a security vulnerability in Bede's code

Found a genuine vulnerability in the codebase itself (not an incident on
your own running instance)? Use GitHub's private vulnerability reporting
on this repository rather than a public issue — it goes directly to the
maintainers without disclosing the details publicly first.

> **Setup note for maintainers:** private vulnerability reporting has to be
> turned on per-repository (GitHub repo → Settings → Security → "Private
> vulnerability reporting") — this document assumes it's enabled, but
> that's a one-time manual step outside anything a codebase change can do.
> A root-level `SECURITY.md` pointing here is the other half of making this
> channel discoverable — GitHub surfaces it under the repo's "Security" tab
> automatically once one exists.

## Accountability

| Area | Who | Channel |
|---|---|---|
| A specific family's self-hosted instance | That family (the parent) | Their own `PARENT_EMAIL` alerts + audit log |
| The public demo | Whoever deploys/operates it | `FEEDBACK_EMAIL` |
| A vulnerability in Bede's code | Project maintainers | GitHub private vulnerability reporting (see above) |

This mirrors `docs/CONSTITUTION.md`'s change-control section for a
different kind of change (the constitution's *substance*, not a security
incident) — see that document if what you're dealing with is a proposed
change to Bede's persona or ethical rules rather than a security event.
