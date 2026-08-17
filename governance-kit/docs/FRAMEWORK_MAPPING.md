# Framework Cross-Map

Where each part of this kit lands against the **OWASP Top 10 for LLM
Applications** and the **NIST AI Risk Management Framework**.

**Read this as a gap-finding tool, not an attestation.** A mapping is useful for
noticing that you have nothing at all against LLM04, and useless as evidence
that you have handled LLM01. Nobody handles LLM01.

---

## OWASP Top 10 for LLM Applications

| ID | Risk | Kit coverage | Honest status |
|---|---|---|---|
| **LLM01** | Prompt Injection | [G08](../prompts/G08-untrusted-content-envelope.md) envelope + `sanitization.py`; [G06](../prompts/G06-tool-use-discipline.md) trust tiers; [G12](../prompts/G12-moderation-classifier.md) classifier; [G01](../prompts/G01-constitution-preamble.md) constitution re-sent every round | **Mitigated, never solved.** The real control is confinement: decide who reads the output if an injection succeeds. Filters are depth. |
| **LLM02** | Sensitive Information Disclosure | `redact_credentials()` applied wherever free text enters context, logs, or storage; [G03](../prompts/G03-ethical-boundaries.md) rules 4–5 | Strong for credential shapes. Says nothing about your own data model — that is your classification work. |
| **LLM03** | Supply Chain | Out of scope here | Not a prompt problem. Pin dependencies with hashes, gate on a lockfile-freshness check, generate an SBOM. |
| **LLM04** | Data and Model Poisoning | [G11](../prompts/G11-certainty-and-verbatim.md) verbatim catalogs; content-curation gating | **Partial.** Verbatim catalogs stop the model improvising text that must be exact. Poisoning of the base model is not addressable from here. |
| **LLM05** | Improper Output Handling | [G06](../prompts/G06-tool-use-discipline.md) — tool results are server-computed structured data, never free text | Strong, *because* of the trust tier. If any tool returns free text, this row is not covered for you. |
| **LLM06** | Excessive Agency | [G06](../prompts/G06-tool-use-discipline.md) caps, terminal tools, unknown-name defaults; [G01](../prompts/G01-constitution-preamble.md) authority order; per-action privilege elevation | Strong. The authority order is the underrated part: most agency failures are misresolved conflicts, not forbidden actions. |
| **LLM07** | System Prompt Leakage | [G03](../prompts/G03-ethical-boundaries.md) rule 4; Tier-1 exfiltration patterns; classifier category | **Mitigated, not solved.** The durable answer is holding no secret in the prompt. Treat your system prompt as public and design so leaking it costs nothing. |
| **LLM08** | Vector and Embedding Weaknesses | [G08](../prompts/G08-untrusted-content-envelope.md) applies to retrieved chunks | **Partial.** The envelope and sanitization apply. Index poisoning and cross-tenant retrieval leakage are your retrieval layer's problem. |
| **LLM09** | Misinformation | [G11](../prompts/G11-certainty-and-verbatim.md) in full; [G01](../prompts/G01-constitution-preamble.md)'s never-fabricate rule | Strong for quoting and attribution. Does not make the model correct. |
| **LLM10** | Unbounded Consumption | [G06](../prompts/G06-tool-use-discipline.md) loop caps; per-actor message quotas | Strong once both are present. Note that a **rate limit bounds request rate, never aggregate spend** — a session sustained at your rate ceiling for a full token lifetime is unbounded cost. You need a hard per-actor ceiling as well, checked *before* the model call so an over-quota turn costs a database read rather than an inference. |

### The two rows people get wrong

**LLM01 is not solvable by filtering.** Every input filter is a pattern someone
enumerated, and the attack space is natural language. Teams that treat their
filter as the control build features on the assumption it holds. The control is
deciding, structurally, that untrusted content can only reach a context where a
successful injection is survivable.

**LLM07 is mostly a design problem.** You can add extraction patterns and a
refusal rule, and both are worth having. But an agent whose prompt contains
nothing worth stealing has solved this row, and one whose prompt contains a
credential has not solved it no matter how many patterns it matches.

---

## NIST AI Risk Management Framework

The four functions, and what this kit actually contributes to each.

### GOVERN — the culture and process around the risk

| Sub | Kit contribution |
|---|---|
| GOVERN 1.1–1.2 | The constitution as a versioned artifact under documented change control; `amendment_policy.required_change_control` |
| GOVERN 1.3 | The authority order — an explicit, written statement of who decides what |
| GOVERN 2.1 | The named accountable owner in the change-control list |
| GOVERN 4.1 | [`PHILOSOPHY.md`](PHILOSOPHY.md) §7 — stating limits in the artifact rather than the pitch |

This is the function the kit contributes to most, and the one most agent-safety
tooling ignores entirely. Governance is mostly *process that leaves a record*,
and a digest-pinned constitution with mandatory review is exactly that.

### MAP — knowing what you built and what could go wrong

| Sub | Kit contribution |
|---|---|
| MAP 1.1 | [`THREAT_MODEL_TEMPLATE.md`](THREAT_MODEL_TEMPLATE.md) — including the non-goals, which are as binding as the goals |
| MAP 2.2 | The tool registry as a declarative inventory of every capability |
| MAP 3.4 | [G10](../prompts/G10-substitution-limits.md) — naming what the agent must not replace |
| MAP 5.1 | [`ADOPTION.md`](ADOPTION.md) Phase 0 question 1: who is harmed, and can they tell? |

### MEASURE — evaluating what you claim

| Sub | Kit contribution |
|---|---|
| MEASURE 2.7 | Adversarial evaluation sets per prompt block; the false-positive corpus |
| MEASURE 2.11 | [G09](../prompts/G09-measurement-refusals.md) — refusing to compute what you cannot compute fairly |
| MEASURE 4.2 | Verify-by-breaking: a control's test must fail when the control is removed |

**The kit's own position on MEASURE is a caution.** Most of what matters here is
not measurable by a benchmark. You can measure classifier precision; you cannot
measure whether your authority order is right. Do not let the measurable parts
set your priorities.

### MANAGE — responding when it goes wrong

| Sub | Kit contribution |
|---|---|
| MANAGE 2.2 | Fail-open classifiers with a deterministic tier underneath — degraded, never off |
| MANAGE 2.3 | Audit every decision; alert on sustained patterns rather than single flags |
| MANAGE 2.4 | [G05](../prompts/G05-safeguarding-escalation.md) — a named human destination, not "escalate appropriately" |
| MANAGE 4.1 | Both write-path and read-path sanitization, because past records survive the fix |

---

## What no framework in this table covers

Worth saying, because a completed cross-map creates a feeling of coverage that
the map itself does not justify:

- **Whether your values are the right values.** Nothing here validates that. A
  well-governed agent with bad values is a well-governed bad agent.
- **Whether the measurement you refused was the one worth refusing.** [G09](../prompts/G09-measurement-refusals.md)
  gives you the pattern; naming your domain's forbidden metric is judgment.
- **Whether "helpful" and "safe" were traded correctly for your users.** Every
  redirect is a real person not helped. That ratio is a product decision, and
  the frameworks are silent on it.
