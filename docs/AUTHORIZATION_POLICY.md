# Authorization Policy

Every authorization decision Bede makes, as one table. This is the artifact
`docs/ARCHITECTURE_PRINCIPLES.md` P7 requires ("authentication,
authorization, and audit are distinct functions, independently verifiable")
— the thing an auditor or an incoming pentest team asks for when they want
to know what a given role can actually do.

Before this existed, the answer required reading 67 `Depends(...)` call
sites plus five inline `role == "..."` comparisons buried in router bodies.
Those five were real authorization decisions living outside the dependency
layer, invisible to anyone auditing authorization by reading `core/deps.py`.

## The layers

```
core/security.py   authentication   is this token genuine, and issued to this device?
core/policy.py     authorization    may this subject take this action?          <- pure
core/deps.py       enforcement      allow the request, or raise
core/audit.py      audit            record what happened
```

`core/policy.py` is pure — no I/O, no FastAPI types, no database. That's
what makes the table below testable exhaustively rather than inferable, and
it's the property to preserve if this is ever extended.

**Session liveness is deliberately not a policy decision.** Whether a demo
code still exists server-side needs a database read, so it stays in
enforcement. Policy answers *may this subject do this*; enforcement
additionally answers *is this session still real*.

## Subjects

| Role | Identity domain | Meaning |
|---|---|---|
| `parent` | family | Account holder and administrator. Today these are the same identity with no elevation between them — see P8 |
| `child` | family | Student session |
| `demo_code` | demo | Pseudonymous public-demo visitor, one-time code |
| `parent_pending` | family | Transient: password verified, second factor outstanding |
| `parent_recovery` | family | Transient: ≥2 recovery factors proven, may only set a new password |

`identity_domain` is a first-class subject attribute rather than something
derived from the role string at each use. That's the seam for P10 (distinct
trust domains get distinct identity domains): the table already reasons in
terms of domains, so separating *issuance* later becomes a change to
authentication rather than a rewrite of every authorization decision.

## Decision table

| Action | parent | child | demo_code | Notes |
|---|:--:|:--:|:--:|---|
| `session.self` | ✅ | ✅ | ✅ | Validate, logout |
| `tutor.chat` | ✅ | ✅ | ✅ | Demo's session config is substituted server-side — an input-handling concern, not authz |
| `tutor.email_summary` | ✅ | ❌ | ✅ | A child must not be able to send mail to an arbitrary address |
| `family.data.read` | ✅ | ✅ | ❌ | Student configs, transcripts, narration, voice profiles, diagnostics |
| `family.data.write` | ✅ | ✅ | ❌ | |
| `admin.manage` | ✅ | ❌ | ❌ | Audit log, licensing, AI provider, student deletion |
| `sandbox.parent_chat` | ✅ | ❌ | ❌ | Additionally gated by `SANDBOX_PIN` — a second factor, not an authz question |
| `sandbox.demo_preview` | ❌ | ❌ | ✅ | Demo domain only, deliberately not reachable by a family session |
| `diagnostic.demo_preview` | ❌ | ❌ | ✅ | Same |
| `mfa.complete` | ❌ | ❌ | ❌ | `parent_pending` only |
| `recovery.reset_password` | ❌ | ❌ | ❌ | `parent_recovery` only |

Transient roles get exactly one action each and are denied everything else.

## Deny by default

An unknown action, an unknown role, or a role not explicitly listed is
**denied**. This matters more than it might seem: the previous model was the
inverse in practice — guards rejected specific known-bad roles and let
everything else through — and that is exactly how the gap below arose.

### The gap this closed

`require_auth` rejected `parent_pending` by name and said nothing about
`parent_recovery`. So a recovery token — issued only after proving 2 of 3
recovery factors, and intended for exactly one action (setting a new
password) — **passed `require_auth` and could reach any of the 17 endpoints
behind it.**

The fix isn't a new check; it's the inversion. Enumerating transient roles
and granting each only its own action makes this class of gap structurally
impossible rather than something to remember for each new guard.

Regression: `tests/test_deps_policy_equivalence.py::test_parent_recovery_no_longer_passes_require_auth`.

## Guards

| Guard | Action enforced | Liveness checked |
|---|---|:--:|
| `require_auth` | `session.self` | ✅ |
| `require_real_user` | `family.data.read` | ✅ |
| `require_parent` | `admin.manage` | — |
| `require_email_summary` | `tutor.email_summary` | ✅ |
| `require_demo_preview` | `sandbox.demo_preview` | ✅ |
| `require_mfa_pending` | `mfa.complete` | — |
| `require_parent_recovery` | `recovery.reset_password` | — |

The last two guards replaced inline router checks:
`require_email_summary` for `routers/tutor.py`'s
`role not in ("parent", "demo_code")`, and `require_demo_preview` for
`routers/sandbox.py`'s `role != "demo_code"` and
`routers/diagnostic.py`'s `_require_demo_code` helper.

## What this deliberately does not do

Scoped out, each its own step that this layer makes reachable:

- **P8 — step-up / privileged access.** `parent` is still simultaneously the
  ordinary account identity and the fully-privileged administrative one.
  Naming `admin.manage` separately from `family.data.*` is what gives an
  elevation check somewhere to attach; building it is separate work.
- **P9 — device identity.** Sessions still bind to `SHA-256(IP | UA)`, not a
  per-device keypair, so a lost tablet can't be individually revoked.
- **P10 — identity domain separation.** Both domains are still issued by one
  signing key and validated by one path. The subject attribute is the seam,
  not the fix.
- **Punch-list #7 — child PIN lockout.** Deliberately sequenced *after* this
  layer so it lands inside a real policy layer rather than extending the
  collapsed one, and so it can be designed around the lockout-as-DoS
  tradeoff documented in `docs/THREAT_MODEL.md` rather than mechanically
  copying `core/parent_lockout.py`'s fixed-threshold pattern.

## Tests

| File | Covers |
|---|---|
| `tests/test_policy.py` | The full role × action matrix (55 pairs), fail-closed behavior, transient-role scoping, denial-message preservation, domain modeling, immutability |
| `tests/test_deps_policy_equivalence.py` | Every guard, per role: status codes and user-visible messages identical to before the refactor, liveness ordering, and the two deliberate behavior changes asserted explicitly |

Adding an action to `core/policy.py` without a row in `test_policy.py`'s
expected matrix fails `test_documented_matrix_covers_every_action_in_the_table`
— the table can't grow an untested entry.
