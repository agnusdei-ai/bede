# Bede ↔ Locuto connector: pre-implementation decision packets

> **Format borrowed deliberately from `agnusdei-ai/locuto`'s own `docs/decision-packets.md`** —
> exact question, why it's open, options with cost and assessment, dependencies, affected claims,
> and a recommendation that is an argument, not a ruling. **Neither packet below is decided.**
> Nothing in `services/tool_registry.py` or `services/adapters/` should change on the strength of
> a recommendation here; that requires the same founder review this codebase's standing workflow
> already requires for an architecturally significant change.
>
> Companion to `agnusdei-ai/locuto`'s `docs/bede-connector.md` (merged) — that document proposed a
> capability schema conditional on `agents.md` §9 open question 1 (whether a content agent should
> exist at all) resolving yes. These two packets are blockers discovered on Bede's own side while
> asking what implementing that schema would actually require, and they stand regardless of how
> quickly §9.1 resolves — packet 1 is Bede's alone to decide; packet 2 needs both teams, since it
> bears directly on `agents.md` §5's own measurement guarantee.

---

## 1. Which of Bede's model adapters may a Locuto-content-touching capability call, and how is that enforced?

**RESOLVED — option A, a dedicated fail-closed local-only resolver.** Implemented as
`resolve_local_only()` in `services/adapters/router.py`: bypasses `_order()`,
`BEDE_FORCE_ADAPTER`, and `core/provider_state.py`'s live override entirely rather than merely
reordering around them, so no household configuration — present or future — can route a
Locuto-content-touching call through a commercial adapter. Raises
`LocalAdapterUnavailableError` (never falls back) when `LOCAL_LLM_BASE_URL` isn't configured;
builds a fresh client per call rather than caching, so it can never share state with whatever
client ordinary tutoring turns are using. Covered by seven tests in
`tests/test_provider_adapters.py` (a new "resolve_local_only()" section), including explicit
proof that it ignores `BEDE_ADAPTER_ORDER`, `BEDE_FORCE_ADAPTER`, and a live DB override even
when each would otherwise point at a configured, higher-priority cloud adapter.

**This closes only what packet 1 asked** — the resolver exists and is proven independent of
household configuration. `agents.md` §9 open question 1 has since resolved
(`open-decisions.md` decision 167 — see packet 2's premise note above), and Locuto's
`docs/bede-ipc-spec.md` (merged in Locuto PR #47) has since specified the local-IPC listener and
named this exact function as the required resolution path (§6).

**A caller now exists.** `services/locuto_ipc/` implements Bede's half of that spec — a
Unix-domain-socket listener (framing, handshake, per-connection dispatch) as its own process,
separate from the main `api` container (`bede-connector.md` §2). `_dispatch_request()` is the
single place a `Request`'s capability is looked up and invoked, and where `resolve_local_only()`
gets its first real caller: any future capability handler must go through it, and
`LocalAdapterUnavailableError` translates to the wire's `Unavailable` outcome rather than being
retried against a different adapter. **The capability registry is still deliberately empty** —
no capability has an exact CBOR schema specified in either repo yet (bede-ipc-spec.md §4: "never
a widening of an existing" message body), so registering one here would mean inventing a schema
unilaterally. What ships is a tested protocol skeleton — transport, framing, peer-credential
check, handshake, and the §6 enforcement point — with zero actual agent behavior.
`resolve_local_only()` has a caller now, but that caller still dispatches nothing real.

**The listener ships enabled by default.** `LOCUTO_IPC_ENABLED` defaults `true` and the
`locuto-ipc` docker-compose service starts with the rest of the stack — Bede is meant to
interoperate with a paired Locuto installation out of the box, a deliberate departure from this
codebase's usual "empty/off = disabled" convention. Safe only because of the empty registry
above: a deployment that never pairs with Locuto gets a socket that completes a handshake and
refuses every real capability, nothing more. A deployer can still set `LOCUTO_IPC_ENABLED=false`
(install time or later, restart required) to disable it outright; a disabled listener idles
rather than exiting, so that choice can't turn into a restart-loop. See
`services/locuto_ipc/__init__.py` and `server.py`'s own docstrings.

Left below unedited otherwise, as the record of the question and the options it was closed against.

**Exact question.** When a capability like `PrepareUserReviewableSendDraft` needs a model call to
draft, summarize, or search Locuto-supplied plaintext, which of Bede's configured adapters
(`services/adapters/`) may that specific call use, and what stops it from using any other?

**Why it is open.** Bede's adapter router resolves one client per deployment
(`resolve_with_failover()`/`get_default_client()`, ordered by `BEDE_ADAPTER_ORDER`, live-overridable
via `core/provider_state.py`), and every existing call site — `stream_tutor_response`,
`stream_sandbox_response`, the moderation classifier — shares that same resolution. There is no
per-call-site override today that pins one specific call to local-only regardless of the
household's general configuration. The library default is `local,anthropic`, and any household
without a local GPU running Bede on Anthropic — the common case — would have a naively-added
Locuto capability route straight to a commercial API by default. `bede-connector.md` §3 requires
this never happen for Locuto content "regardless of contractual terms," matching
`storage.md` §10.2's own language on the Locuto side — this cannot be left to household
configuration to get right, because a family reconfiguring their adapter order for ordinary
tutoring reasons would silently break the boundary for an unrelated feature they never touched.

| Option | Cost | Assessment |
| --- | --- | --- |
| **A. A capability-scoped forced-local resolver** — a new function that only ever returns the local adapter client, and refuses (never falls back to cloud) if `LOCAL_LLM_BASE_URL` isn't configured. This capability's call site imports nothing else. | One new, narrowly-scoped resolution function; the capability is simply unavailable on a household with no local model configured, matching `bede-connector.md`'s own "unavailable rather than silent fallback" rule and `host-connector.md` §4.1's identical philosophy on Locuto's side | Matches the written boundary exactly. The only option that fails closed rather than fails silent |
| **B. Reuse the shared, currently-resolved client**, same as ordinary tutoring | Zero new code | **Rejected outright** — the exact violation §3 exists to prevent, for the majority of self-hosted households |
| **C. Require a local adapter at capability-registration/pairing time, then reuse whichever adapter is primary** | A one-time check rather than a per-call one | Weaker than A: `BEDE_ADAPTER_ORDER` is a live, no-restart override (`core/provider_state.py`) — a parent moving Anthropic to primary *after* pairing silently reopens the leak, since nothing re-checks |

**Depends on:** `services/adapters/router.py`'s existing resolution functions; `core/provider_state.py`'s
live-override precedence; whether the household has a local adapter configured at all — worth
stating plainly that most self-hosted families on a GPU-less machine cannot satisfy this capability
today, which is a real product constraint, not just an implementation detail.

**Claims affected.** `bede-connector.md` §3's "no Locuto plaintext... over a network transport...
including a model API" is currently unenforceable by anything in Bede's code. This packet is what
would make that claim actually true rather than aspirational.

**Build/config impact.** A: one new function, one new call site, zero change to any existing
tutoring path, nothing on Locuto's side. B/C: none beyond what's noted above.

**Recommended.** **A.** It's the only option that makes the existing written claim true regardless
of household configuration, fails safe, and costs a small, isolated addition rather than touching
anything already shipping.

---

## 2. Does a Bede companion need to satisfy `agents.md` §5's measurement requirements, and if so, how?

> **Premise update, not a resolution: `agents.md` §9 open question 1 has resolved yes.**
> `agnusdei-ai/locuto`'s `docs/open-decisions.md` decision 167 (owner ruling, 2026-08) permits a
> content agent to be built at all, conditioned on the containment `agents.md` §4 already specifies
> (may read and advise, may never act) and the monitoring `bede-connector.md` §7 already specifies
> (metadata-only audit, one revocation switch) holding as load-bearing requirements. It does not
> choose Bede as the candidate, and it does not resolve this packet's own question — but this
> packet's recommendation below was written when §9.1 "hasn't resolved yes yet," and that premise no
> longer holds. Left below unedited otherwise: the recommendation is not changed by this note, since
> whether to build A now is a real timeline and resourcing call for this project's own owner, not
> something a premise change alone decides. Cross-referenced from Locuto's own
> `docs/decision-packets.md` packet 12, which independently reaches this same question from Locuto's
> side and verified `resolve_local_only()` (packet 1, resolved below) as real against this
> repository's actual source rather than assuming it. The wire-level transport this packet's
> eventual answer would need to travel over — once a capability call site exists to use it — is now
> specified at `agnusdei-ai/locuto`'s `docs/bede-ipc-spec.md`; neither side has implemented it.

**Exact question.** `agents.md` §5 requires a locally-composed agent's runtime (signed), weights
(hash-pinned), and policy (hash-pinned), so Locuto's peer-side detection layer
(`multi-device.md` §7.2b) can surface a tampered agent. Bede has none of this today. Does shipping
require Bede to build equivalent infrastructure first, accept a disclosed, narrower guarantee for
third-party companions specifically, or hold the whole feature until Locuto's own detection layer
is confirmed to extend to this case at all?

**Why it is open.** A genuine mismatch between two products' release models, not an oversight in
either. Bede is presently self-hosted-from-source or installed via a packaged installer, with no
code-signing, no reproducible-build attestation, and no hash-pinned weight manifest for any
supported backend — Anthropic/OpenAI/Mistral don't apply (no local weights), and the local
vLLM/Ollama path's own integrity story (content-addressed pulls via Ollama's registry, per
`docs/PROVIDER_ADAPTERS.md`'s LLM04 note) is a different *kind* of guarantee than a
Locuto-issued hash pin, not an equivalent one. If Bede is admitted as a content agent with nothing
matching §5, a silently-modified companion is invisible to the exact layer this integration is
meant to sit inside — the risk §5 itself names: *"an agent surface that is not covered by that
measurement defeats it locally."*

| Option | Cost | Assessment |
| --- | --- | --- |
| **A. Build a real signed-release + reproducible-build pipeline for the companion specifically** — not the whole Bede tutoring stack, a narrowly-scoped connector process per `bede-connector.md` §2's own recommendation that this shouldn't run inside Bede's main API container | Substantial: a signing key, a CI/release pipeline, a policy-hash manifest, and — unspecified on either side today — how Locuto's own peer-detection layer would actually observe and recognize a Bede-signed artifact | The only option that makes §5 true for this pairing. Also the slowest and most expensive |
| **B. Ship without equivalent measurement, disclosed explicitly** as a stated limit in whatever consent/disclosure text covers this feature (extending both `bede-connector.md` and `compliance/direct-notice-to-parents.md`) | None technically; a real, named weakening of the security claim | Consistent with this whole effort's own ethos — *"an honest 'this has not been checked' is worth more than a confident answer"* — **only if disclosed, never if assumed silently** |
| **C. Hold the content-agent feature until A exists**, treating §5 compliance as a hard gate | Delays everything in `bede-connector.md` on infrastructure unrelated to the capability schema itself | The safest reading of §5's own words, and the one most consistent with "not covered by that measurement defeats it locally" — but a real timeline cost only the two products' owners can weigh |

**Depends on:** `agents.md` §5 and its own open question 1 (moot if that resolves no);
`multi-device.md` §7.2b's actual detection mechanism, not read in detail here and worth confirming
before assuming A's shape is sufficient; Bede's pre-existing lack of any release-signing
infrastructure, which this packet doesn't propose fixing for its own sake, only in service of this
integration.

**Claims affected.** `agents.md` §5's own statement that an unmeasured surface defeats the
detection layer locally — true of a Bede companion under B or C, untrue only under A.

**Build/config impact.** A: substantial new infrastructure on Bede's side, with a coordination
dependency on Locuto's own detection layer that neither side has specified yet. B/C: no code, a
disclosure-text decision or a schedule decision respectively.

**Recommended.** **C in the near term** — building A's real signing infrastructure is premature
while Locuto's own §9.1 hasn't resolved yes yet — **with B as the honest fallback if the org
decides to ship before A exists, never as a silent default.** A remains the right eventual target
if the feature is built at all.

---

## What is not in here

**No signing infrastructure, and no real capability.** Packet 1 is the one exception to "no code,
no adapter-router change": its resolution shipped `resolve_local_only()`, verifiable in isolation
without the connector it would eventually serve — and `services/locuto_ipc/` (see packet 1's
closing note) is that connector's transport skeleton, dispatching to an intentionally empty
capability registry. Neither is a capability: no Locuto plaintext has ever reached this process,
and none can until a specific capability's CBOR schema is specified and a handler registered — a
separate, deliberate change this document doesn't pre-authorize. Packet 2 remains a question with
a recommendation attached, not a decision — matching Locuto's own convention that a recommendation
here is an argument the owner may reject.
