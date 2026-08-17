# Agent Hardening Checklist

Work through it once for a new agent, and again whenever you add a capability.
Items marked **⚠** are the ones most often skipped and most often regretted.

Skip anything that does not apply to your system, and write down *why*, because
a skipped item with a stated reason is a decision, and a skipped item without one
is an oversight nobody can distinguish from a decision later.

---

## Foundation

- [ ] Values live in a **separate artifact**, not inline in a prompt string
- [ ] The artifact is **digest-pinned in code**
- [ ] Verification runs at **process start** and is **fatal** on failure
- [ ] ⚠ **Structure** is validated independently of the digest: this is the only
      check that catches a same-commit edit of both file and pin
- [ ] Loaded values are **immutable in memory** (recursively read-only)
- [ ] The preamble is rendered into **every** prompt that shapes behavior.
      Grep for every prompt builder, including the summarizer and any internal
      or admin path
- [ ] An **`authority_order`** exists, and the agent is last in it
- [ ] The **anti-override rule enumerates its channels** (user, operator,
      document, tool result, custom prompt)
- [ ] The **escalation rule names a human destination**, not "appropriately"
- [ ] ⚠ If your values derive from a specific tradition, a **scoping clause**
      states they govern the agent's own conduct
- [ ] Change control is written down and includes **re-pinning in the same
      commit**

## Prompt blocks

- [ ] Every block is in the **cached static block**, and it is byte-identical
      across loop rounds
- [ ] The central discipline has an explicit **no-exceptions clause** naming
      exception-negotiation as a manipulation attempt
- [ ] **Role limits enumerate** the roles the agent must not occupy
- [ ] ⚠ "Do not answer a **smaller version** of the refused question instead" is
      stated; this is the most common real breach
- [ ] Persona reassignment is named as manipulation, and the agent **does not
      argue** about it
- [ ] The architecture-disclosure refusal is **short and unbothered**, and also
      covers describing guardrails "in general terms"
- [ ] The operator-conflict rule says **decline this instruction and continue
      with the rest**, so one bad instruction is not a denial of service

## Detection

- [ ] ⚠ A **deterministic tier** exists with no external dependency
- [ ] Deterministic patterns are **curated for near-zero false positives**
- [ ] Safety-of-person patterns are tuned the **opposite** way: false positives
      are cheap, false negatives are not
- [ ] ⚠ Patterns exist in **every language your product supports**, checked
      **unconditionally** rather than gated on a configured locale
- [ ] The classifier prompt states **"You are NOT the agent"** and forbids
      following instructions in the content
- [ ] Content being classified is **delimited**
- [ ] The classifier **fails open**, with a timeout and a token cap
- [ ] Sentinels are **skipped**, not classified
- [ ] Detection is **separate** from policy
- [ ] The policy function is **pure**: no I/O
- [ ] ⚠ Categories are **tiered**: some block, some are audit-only at any
      confidence, and the assignment was argued about
- [ ] Every decision is **audited**, blocking or not
- [ ] Alerts fire on a **sustained pattern**, not a single flag

## Agent loop

- [ ] Every tool has a declared **trust tier**
- [ ] ⚠ A test asserts **every tool in the user-facing registry is internal**
- [ ] Every predicate returns **`False` for unknown names**
- [ ] `MAX_TOOL_CALLS_PER_TURN` spans **all rounds combined**
- [ ] `MAX_TOOL_LOOP_ROUNDS` exists and is independent
- [ ] ⚠ Hitting the call cap **also ends the loop** (a suppressed `tool_use` can
      never get a matching `tool_result`)
- [ ] Suppressed calls are **audited and alerted on**
- [ ] Only genuinely **dynamic** results extend the loop
- [ ] The continuation rule tells the model a tool result is **not a new
      message**
- [ ] ⚠ Within-turn repetition is guarded **in the dispatch branch**: state
      computed once per turn is stale by round 2, because the cached block is
      re-sent
- [ ] Every dispatched call is **audited**

## External content

- [ ] ⚠ You have answered: **if an injection here fully succeeds, who reads the
      output?**
- [ ] External content is **structurally unreachable** from your most vulnerable
      surface
- [ ] Requires **two switches** to arm
- [ ] Credentials redacted → injection stripped → **length bounded** → enveloped
- [ ] Tool names are **namespaced** so shadowing is impossible
- [ ] The client declares **no `sampling` capability**
- [ ] External invocations are a **distinct audit event** with a tighter
      threshold
- [ ] No subprocesses are spawned

## Persisted text

- [ ] ⚠ For every persisted field, you have asked: **is this replayed into
      prompt context?**
- [ ] Replayed text is sanitized on **both write and read paths**
- [ ] Credentials are redacted wherever free text enters **context, logs, or
      storage**
- [ ] Adding a persisted field is a **threat-model review trigger**

## Measurement

- [ ] You have named **what this agent must not measure**, and it fails a test
- [ ] **Events** and **claims about a person** are stored separately
- [ ] A **blank is visibly distinct** from a low score
- [ ] Panels **report a presence, never an absence**: no zero rows
- [ ] Multi-person views have **no per-person total**, order **independent of
      counts**, and absent-rather-than-zero
- [ ] Distributions, **never averages** over ordinal scales
- [ ] **Every scale floor is a real outcome**: no "poor", no "slow"
- [ ] ⚠ Refusals are written into the **tool descriptions a consuming model
      reads**, with a test asserting they are still there
- [ ] Stored enum values are **frozen**; labels and criteria are revisable

## Consumption

- [ ] A **hard per-actor ceiling** exists, not only a rate limit: a rate limit
      bounds request rate, never aggregate spend
- [ ] The quota is checked **before** the expensive call
- [ ] Over-quota returns a **plain, localized message**, audited

## Testing

- [ ] ⚠ Every guardrail block has a **string-pin test**: no functional test
      catches deleted prompt prose
- [ ] ⚠ Every guard was **verified by breaking** the thing it guards
- [ ] Tests read the **real object**, not a reconstructed replica
- [ ] Stubs validate against the **real contract** (the actual schema or model)
- [ ] ⚠ The **call site** is tested, not just the function: pass a sentinel and
      observe it downstream
- [ ] Wiring that only exists in another runtime is tested **there**
- [ ] A **false-positive corpus** from real traffic, reviewed by hand
- [ ] Evaluations are **re-run when you change models**

## Documentation

- [ ] A threat model exists, with **non-goals** and **self-defeating
      mechanisms**
- [ ] Every control's **limits are stated in the artifact**, not the pitch
- [ ] Approximations **say so where the number is displayed**
- [ ] Someone who is not you could find out **what this system does not cover**
