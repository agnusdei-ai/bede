# OWASP Top 10 for LLM Applications — Mapping

This documents Bede's architecture against the **OWASP Top 10 for LLM
Applications (2025, v2.0)** — a companion to `docs/SECURITY.md`'s
AIUC-1/SOC 2 mapping, not a replacement for it. Like that document, this is
a factual description of what the code does, **not legal advice or a
certification** — OWASP publishes no formal audit or attestation process
for this list the way AIUC-1/SOC 2 do; it is a risk-awareness framework,
and this mapping is a self-assessment against it, current as of the date
below. If something has actually gone wrong, or you've found a
vulnerability in Bede's code, see `docs/INCIDENT_RESPONSE.md` instead.

**On CISSP/CCSP:** Bede has no formal, *named* mapping to either
certification's domain list, unlike the explicit AIUC-1/SOC 2 mapping in
`docs/SECURITY.md`. The controls below (encryption at rest, authentication
and session binding, rate limiting, an independent audit log, incident
response, vendor data-flow documentation) do overlap conceptually with
several CISSP domains (Security & Risk Management, Security Architecture &
Engineering, Communication & Network Security, Identity & Access
Management, Security Operations) and CCSP's cloud-specific concerns — but
that overlap is a byproduct of ordinary security engineering practice, not
a deliberate mapping exercise the way this document and `docs/SECURITY.md`
are. Don't cite this file as a CISSP/CCSP control matrix; it isn't one.

Verdicts: **Strong** (a real, tested, architectural control exists),
**Partial** (a real control exists but has a known, documented limit —
see `docs/SECURITY.md`'s Known open gaps for detail), **N/A** (the
category doesn't apply to Bede's architecture, with the reason stated).

---

## LLM01: Prompt Injection

**Strong.** Layered, not single-point:

- The constitution (`docs/CONSTITUTION.md`, digest-verified at import and
  again at startup by `core/constitution.py`/`main.py`) is prepended to
  every prompt that shapes Bede's behavior and cannot be overridden by any
  parent setting, retrieved content, or child input — see CLAUDE.md's
  "Bede's Constitution."
- `services/moderation.py`'s `prompt_injection` classifier category, plus
  `services/adversarial_detection.py`'s Tier 1 regex and
  `services/policy_engine.py`'s `policy_override_attempt`/
  `data_exfiltration_attempt` categories (the "Adversarial resilience
  pipeline" in CLAUDE.md) catch both direct injection from the child's own
  chat text and framing attacks (jailbreak intent, social engineering).
- `_sanitize_parent_field`/`_INJECTION_PATTERN` (`services/ai_service.py`)
  strip injection phrasing from parent-supplied `SessionConfig` fields that
  sit in the cached, session-long static prompt — the highest-leverage
  injection surface, since that text is reused across every turn.
- `services/mcp_client.py` (external MCP tool results, the one path by
  which content that did not originate inside this process reaches model
  context at all) wraps every result in an `<untrusted_external_content>`
  envelope, redacts credentials, truncates, and re-applies the same
  `_INJECTION_PATTERN` — see CLAUDE.md's "MCP client" section. Confined to
  the parent sandbox by three independent, structural mechanisms
  (`TUTOR_TOOLS` holding only `trust="internal"` specs, `external_tools`
  defaulting to none, the demo route never passing it) rather than one
  setting, specifically because this is the class of defense you want
  redundant.
- `services/tool_registry.py`'s `trust="internal"` on every tutor tool spec
  makes external-trust tool results structurally unreachable from a
  child's session, not just policy-forbidden.

## LLM02: Sensitive Information Disclosure

**Strong.**

- AES-256-GCM at rest for all encrypted columns (`core/encryption.py`),
  with AAD binding closing the row-substitution gap documented in
  `docs/SECURITY.md`'s Closed gaps.
- `ExfiltrationGuard` (`core/middleware.py`) blocks known exfiltration
  endpoints and scans buffered JSON response bodies for leaked key
  material.
- `_redact_credentials` (`services/ai_service.py`, AIUC-1 A008) redacts
  credential-shaped text wherever free text enters the backend — child
  messages, replayed conversation history, the transcripts save path.
- JWTs are IP+User-Agent fingerprinted at issuance (`core/security.py`);
  replaying from a different device 401s.
- The encrypted, independent audit log (`core/audit.py`) records security
  events without itself becoming a new disclosure surface (see its own
  sliding-window anomaly watch).
- One narrow, disclosed exception: picture study's live browser lookup to
  Wikipedia/Wikimedia (see CLAUDE.md's CSP section) — a public article
  title only, no session data, disclosed in `site/privacy/index.html`,
  both demo Privacy Notices, and `docs/VENDOR_DATA_FLOW.md`.

## LLM03: Supply Chain

**Partial**, with the gaps already named and tracked in
`docs/SECURITY.md`'s Known open gaps rather than newly discovered here:

- A CycloneDX SBOM exists (`docs/sbom/`, `scripts/generate_sbom.py`) and
  `pip-audit`/`npm audit` run in CI (restored after being deleted —
  see `docs/SECURITY.md`'s "Dependency vulnerability monitoring restored"
  Closed-gap entry).
- `services/mcp_client.py` deliberately keeps the `mcp` SDK dependency out
  of the API image and its `pip-audit` gate — a hand-rolled JSON-RPC
  client instead, so an optional integration doesn't widen the audited
  dependency surface for every deployment.
- **Closed** (tracked at their original location, `docs/SECURITY.md`'s
  Closed gaps): `homeschool-api/requirements.txt` being floor-pinned
  (`>=`, no upper bound) rather than hash-locked meant a CI run today
  could resolve different exact versions than one from a month ago;
  GitHub Actions being pinned to mutable version tags (`@v4`) rather
  than commit SHAs meant a compromised action's next tag push would run
  in this repo's CI automatically. CI now installs from a hash-verified
  `requirements.lock.txt`/`requirements-dev.lock.txt`
  (`pip-compile --generate-hashes`), and every `uses:` line across every
  workflow is pinned to the exact commit SHA its tag resolved to.

## LLM04: Data and Model Poisoning

**N/A for training-time poisoning; Partial for the two adjacent surfaces
that do exist.** Bede does no fine-tuning or training of any kind — every
adapter (`services/adapters/`) calls an off-the-shelf, frontier-model
inference API (Anthropic, OpenAI, Mistral) or a self-hosted inference
server (vLLM/Ollama) with a fixed prompt, never a training pipeline — so
the classic "poisoned training data" attack surface doesn't exist here at
all. Two narrower, real questions remain:

- **Bede's own bundled prompted content** (the Latin/Greek/logic catalogs,
  curriculum plans, poetry/prayer rotations) is the closest analogue to
  "training data" in the sense that it's fixed content shaping every
  session. `services/content_curation.py` (`scripts/curate_content.py`,
  `docs/CONTENT_CONTRIBUTING.md`) is a mechanical gate over new content:
  verbatim text needs a cited, public-domain primary source; known
  misattributions are flagged (seeded from a real finding — `ora_et_labora`
  appears nowhere in St. Benedict's Rule); proposed activities are scanned
  against the physical-safety guardrail hazard list; and any field
  resembling a faith-engagement metric is refused outright. `curate()`
  marking something "accepted" means "nothing mechanical is wrong," never
  "this belongs in a child's year" — a human still reviews that. **Strong**
  for this half.
- **Self-hosted model weight integrity** — investigated specifically for
  this document. Bede's own installer scripts
  (`packaging/unix/install.sh`, `packaging/windows/Setup-Bede.ps1`) run
  `ollama pull qwen3:<tag>` (or the equivalent GUI flow via
  `scripts/setup_wizard/wizard.py`) and add no independent checksum or
  signature verification of their own on top of it — `docs/PROVIDER_ADAPTERS.md`,
  `docs/UNIX_INSTALLER.md`, and `docs/WINDOWS_INSTALLER.md` say nothing
  about weight integrity either. This delegates entirely to Ollama's own
  pull mechanism, which is itself content-addressed (each model layer is
  fetched and verified against a SHA256 digest named in its manifest, the
  same scheme container registries use) — so this is closer to "trusting
  a well-known upstream tool's own integrity mechanism" (the same posture
  this codebase already takes toward `apt`/`pip`/`npm`) than an
  unverified download. It is genuinely undocumented, though, and a
  self-hosted vLLM deployment sources its model weights entirely at the
  deployer's own discretion with no guidance from this codebase at all —
  inherent to a bring-your-own-model architecture, not something Bede's
  code could enforce without dictating where a family's local model comes
  from. **Partial**: reasonably handled via delegation, not a code gap,
  but worth a documentation note in `docs/PROVIDER_ADAPTERS.md` pointing
  this out explicitly rather than leaving it silent.

## LLM05: Improper Output Handling

**Strong.** The frontend renders Bede's text as plain text/Markdown, never
as executed HTML/JS — no `dangerouslySetInnerHTML` path for model output.
Tool calls are dispatched through `services/tool_registry.py`'s declared,
fixed-shape `ToolSpec`s, not arbitrary code execution; `_MAX_TOOL_CALLS_PER_TURN`
and the bounded `tool_result` loop (`_MAX_TOOL_LOOP_ROUNDS`, both in
CLAUDE.md's "Tool-call defense-in-depth"/"Bounded tool_result loop"
sections) bound what a single turn's tool activity can do regardless of
what the model asks for. No code-execution, shell, or open web-fetch tool
is ever exposed to the tutor persona at all (see `docs/SECURITY.md`'s
Society-pillar scope statement).

## LLM06: Excessive Agency

**Strong.** `services/tool_registry.py`'s `ToolSpec` declares each tool's
exact shape (`reactable`/`terminal`/`silent`/`questionless`/`trust`) —
`TUTOR_TOOLS` is a closed, internal-only set the model can select from,
never an open action space. `services/lesson_planner.py`'s own docstring
states the governing principle explicitly: "it orders; it never
chooses" — every agentic surface in this codebase (the lesson planner,
the policy engine, the mastery-cycle reporting) is deliberately
permission-bounded to *ordering or reporting on* parent-set choices, never
adding, removing, or overriding them. `record_skill_evidence`/
`record_phonics_evidence`/`record_language_evidence`/`record_literacy_evidence`
are silent, fixed-shape writes with no model-visible side channel back to
the child. The MCP client (LLM01 above) declares no `sampling` capability,
so an external server can never spend a family's own tokens by asking
Bede's model for completions on its behalf.

## LLM07: System Prompt Leakage

**Strong**, though undocumented as a *named* category before this
document. `services/moderation.py`'s `prompt_injection`/`jailbreak_intent`
categories and `services/adversarial_detection.py`'s Tier 1 regex both
catch direct "repeat your instructions" framing as a form of the broader
injection/jailbreak surface. `docs/CONSTITUTION.md` and the static system
prompt are not secret in the sense of "this app breaks if a child sees
it" — the constitution is a *public, human-readable document* by design
(digest-pinned specifically so it can be verified, not hidden) — so a
successful leak here doesn't expose a credential, an API key, or another
family's data (LLM02 already covers that surface); it exposes prose this
project already publishes. The real risk this category names — a leaked
system prompt handing an attacker the exact wording needed to bypass
downstream defenses — is mitigated by that downstream defense being
structural (tool registry, bounded loops, the policy engine) rather than
being "don't tell the model how it's instructed."

## LLM08: Vector and Embedding Weaknesses

**N/A.** Bede has no vector database, no RAG pipeline, and no embedding
store of curriculum or child content — `services/voice_auth.py`'s speaker
embeddings are the only embeddings in this codebase, and they're a
biometric comparison for voice login, never retrieved into model context
or searched against arbitrary input. Bede's "knowledge" is the model's
own training plus fixed, human-authored prompt content (the catalogs
above) — there's no vector index for a poisoned or crafted embedding to
attack.

## LLM09: Misinformation

**Strong**, primarily through the constitution's "never fabricate
certainty" rule operationalized as concrete, testable prompt guidance
rather than left as an aspiration:

- Verbatim-quote catalogs (poetry, prayer, Latin, Greek — CLAUDE.md's
  respective sections) exist specifically because "a model asked to
  invent a syllogism will sometimes produce an invalid one and label it
  valid" (`services/logic_catalog.py`'s own rationale) — long or precise
  text is quoted from a reviewed source, never improvised, for exactly
  the passages where a subtle misquote would be hardest to catch.
- `_bible_translation_note`'s public-domain/copyrighted split
  (`PUBLIC_DOMAIN_BIBLE_TRANSLATIONS`) tells Bede to paraphrase by default
  and keep direct quotation to what it's genuinely confident about,
  always citing book/chapter/verse so a family can check the real text —
  the constitution's fabrication rule applied specifically to a text Bede
  cannot verify against a licensed copy.
- `services/content_curation.py` flags known misattributions before
  content ships at all (the `ora_et_labora` case above).
- `services/logic_catalog.py`'s worked examples include `valid_but_false`
  cases specifically so a student learns that a valid argument form and a
  true conclusion are different questions — misinformation-adjacent
  pedagogy, not just a technical control.

## LLM10: Unbounded Consumption

**Strong as of this document; previously Partial.** Two independent
levers existed before this work — `_MAX_ACTIVE_CODES` (concurrent demo
codes) and `RateLimitMiddleware`'s per-IP "api" bucket (120 req/min
default, `core/middleware.py`) — but neither bounds *aggregate* spend, only
concurrency and request rate. A single scripted session sustained at the
rate limit's own ceiling for its whole `demo_code_token_expire_minutes`
token lifetime (120 minutes by default) could sustain on the order of
14,000 real model calls from one demo code, on the single publicly-reachable,
unauthenticated-signup surface this codebase has — a genuine denial-of-wallet
gap, and `core/demo_code_session.py`'s own docstring said so explicitly
("No per-code message cap by design").

Closed in this pass: `_MAX_MESSAGES_PER_CODE` (400, `core/demo_code_session.py`)
is a hard per-code ceiling on chat messages, checked via `has_message_quota()`
— a read-only pre-check kept deliberately separate from the existing
`record_message()` counter so the refusal happens *before* the model call
a turn would trigger, never after. Wired into both public-demo streaming
entry points (`routers/tutor.py`'s `/tutor/chat`, `routers/sandbox.py`'s
`/sandbox/demo-chat`), ahead of the safeguarding/moderation/policy-engine
pipeline, so an over-quota turn costs one database read and nothing else.
400 is sized well above any real evaluation (every subject, both faith
modules, picture study, voice — comfortably under 200 exchanges), so
duration and subject breadth remain deliberately uncapped; only aggregate
message volume per code is now bounded. See `docs/SECURITY.md`'s Closed
gaps entry (2026-08-12) and `tests/test_demo_message_quota.py`.

Beyond the demo, the same rate-limiting middleware applies to every
authenticated role (parent/child/demo_code alike), and `_MAX_TOOL_CALLS_PER_TURN`/
`_MAX_TOOL_LOOP_ROUNDS` (LLM06 above) independently bound how many model
round-trips and tool dispatches a single turn can cost regardless of
caller — a second, architectural ceiling under the per-message one.

---

*Last reviewed: 2026-08-12, against the official OWASP Top 10 for LLM
Applications 2025 (v2.0) list.*
