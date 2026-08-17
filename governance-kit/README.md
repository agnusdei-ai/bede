# Agent Governance Kit

**A hardening layer for agents that operate on people who did not consent to be
experimented on.**

This is a portable package of governance prompts, enforcement patterns, and
reference code, extracted from a production agent that tutors children. It is
framework-agnostic — nothing here depends on a particular SDK, model vendor, or
orchestration library. You can adopt one file or all of it.

Licensed under Apache 2.0. Use it, fork it, ship it in a commercial product.

---

## Why this exists

Most agent "safety" work stops at a system prompt that says *be helpful,
harmless, and honest*, plus a moderation API call. That gets you through a demo.
It does not survive contact with a real user population, because a system prompt
is a request and an agent under adversarial pressure treats requests as
negotiable.

The patterns here come from a system where getting it wrong means a specific
child gets hurt, so the design question was never "does this feel safe" but
"what still holds when the model is wrong, the classifier is down, the user is
hostile, and nobody is watching." That constraint produced a set of techniques
that generalize well past the original domain:

- Rules the agent **structurally cannot** override, verified at process start.
- Detection separated from policy, so either can change without the other.
- Tool results that **cannot** carry an instruction, because of where they come
  from rather than because we asked nicely.
- Refusals that travel *with the data*, so a downstream model cannot
  reintroduce a judgment the data does not contain.
- Every control paired with a test that fails when the control is removed.

## What's in the box

| Directory | What it is |
|---|---|
| [`prompts/`](prompts/) | 12 drop-in governance prompt blocks, each with the rationale, the failure it prevents, and the real-world incident that produced it |
| [`templates/`](templates/) | A constitution template + JSON schema you fill in for your own domain |
| [`reference/`](reference/) | Dependency-free Python implementing the enforcement layer (constitution verification, sanitization, two-tier detection, policy engine, tool trust registry, untrusted-content envelope) with tests |
| [`checklists/`](checklists/) | An agent hardening checklist and a PR review checklist |
| [`docs/`](docs/) | The philosophy, a 90-minute adoption path, a framework cross-map (OWASP LLM Top 10 / NIST AI RMF), a threat-model template, and the case study |

## Quickstart

```bash
# 1. Copy the kit into your project
cp -r governance-kit/reference your_project/governance
cp governance-kit/templates/constitution.template.json your_project/constitution.json

# 2. Fill in constitution.json for your domain, then pin its digest
python your_project/governance/pin_digest.py your_project/constitution.json

# 3. Verify at import time — this raises if the file was tampered with
python -c "from governance.constitution import load_constitution; load_constitution()"

# 4. Run the reference tests
python -m pytest governance-kit/reference/tests -q
```

Then work through [`checklists/AGENT_HARDENING_CHECKLIST.md`](checklists/AGENT_HARDENING_CHECKLIST.md).
It is ordered by value-per-hour, not by topic.

## The five ideas, in one screen

**1. A constitution, not a system prompt.** Your agent's non-negotiable values
live in a separate, digest-pinned file, verified for both integrity and
*structure* at process start. A missing or modified constitution prevents the
agent from starting at all. It is rendered into every prompt that shapes
behavior — not just the main one. See [`prompts/G01`](prompts/G01-constitution-preamble.md)
and [`reference/constitution.py`](reference/constitution.py).

**2. Structural guarantees beat policy guarantees.** "We tell the model not to"
is a policy guarantee. "The untrusted tool is not in the registry the loop
dispatches from, so it cannot be called even if the model asks" is a structural
one. Only the second kind survives a model you did not train. See
[`prompts/G06`](prompts/G06-tool-use-discipline.md) and
[`reference/tool_registry.py`](reference/tool_registry.py).

**3. Detection is facts; policy is meaning.** A regex tier and a classifier tier
both emit *what they saw*. One pure function decides what it means. This is why
you can tune false-positive tolerance per category — and why some categories are
audited but never block alone. See [`reference/policy_engine.py`](reference/policy_engine.py).

**4. Sanitize anything that gets replayed.** "User text is transient, so we
leave it alone" holds exactly as long as the text really is transient. The
moment you persist a summary of a conversation the user steered and replay it
into tomorrow's prompt, you have built a stored injection vector. See
[`prompts/G08`](prompts/G08-untrusted-content-envelope.md) and
[`reference/sanitization.py`](reference/sanitization.py).

**5. Refuse to measure what you have no standing to measure.** The hardest
governance problem is not the agent doing something forbidden — it is the agent
computing a number that quietly becomes a verdict about a person. A blank must
not look like a low score. A roster must not become a ranking. And the refusal
has to travel in the tool description the model actually reads, because a
consuming model can reintroduce a ranking the data does not contain just by
summarizing it. See [`prompts/G09`](prompts/G09-measurement-refusals.md).

## What this kit is not

- **Not a compliance product.** [`docs/FRAMEWORK_MAPPING.md`](docs/FRAMEWORK_MAPPING.md)
  maps these controls to OWASP LLM Top 10 and NIST AI RMF because that is useful
  for finding gaps, not because a mapping is an attestation.
- **Not tamper-proof.** The constitution mechanism is tamper-*evident*. Someone
  who can rewrite both the file and the pinned digest in the same commit
  produces a build that verifies against itself. Repository review, protected
  branches, and signed releases are the actual trust boundary. This is stated
  plainly in the code rather than implied away.
- **Not a substitute for red-teaming.** These are the deterministic and
  architectural defenses. Live adversarial probing against your actual persona
  is separate work that this makes cheaper, not unnecessary.
- **Not domain-neutral by accident.** The original system is a Catholic
  classical tutor for children. The prompts here are generalized, and
  [`docs/CASE_STUDY_BEDE.md`](docs/CASE_STUDY_BEDE.md) shows the real filled-in
  versions so you can see what a fully committed instance looks like.

## Contributing

The bar for a new pattern is: **it prevented a real failure, and you can state
the failure.** See [`CONTRIBUTING.md`](CONTRIBUTING.md). Patterns that sound
prudent but have never caught anything make a checklist longer and an engineer
less likely to read it.

## Provenance

Extracted from [Bede](https://agnusdei.ai) — a self-hosted, LAN-deployed
Socratic tutoring agent. Bede is proprietary; this directory is not. See
[`NOTICE`](NOTICE).
