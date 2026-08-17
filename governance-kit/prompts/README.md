# The Prompt Library

Twelve governance blocks. Each file has the same four sections:

1. **What it prevents**: the concrete failure, not a category name.
2. **The block**: drop-in text with `{PLACEHOLDERS}` you substitute.
3. **Adaptation notes**: what to change for your domain, and what not to.
4. **How to test it**: how you verify the guardrail is still there.

## Index

| ID | Block | Prevents | Priority |
|---|---|---|---|
| [G01](G01-constitution-preamble.md) | Constitution preamble | Values that any sufficiently clever prompt can renegotiate | **Start here** |
| [G02](G02-operating-rules.md) | Operating rules | Rule drift under social pressure; "just this once" exceptions | **Start here** |
| [G03](G03-ethical-boundaries.md) | Role limits & anti-impersonation | The agent accepting a role it is not competent or licensed to hold | **Start here** |
| [G04](G04-physical-safety.md) | Physical safety of own suggestions | The agent being the *source* of a dangerous idea | High |
| [G05](G05-safeguarding-escalation.md) | Escalation & crisis handling | Continuing to perform the task through a disclosure that should stop it | High |
| [G06](G06-tool-use-discipline.md) | Tool-use discipline | Unbounded tool loops; a hallucinated tool buying itself round-trips | High |
| [G07](G07-tool-result-continuation.md) | Tool-result continuation | Praising a user for an answer they never gave | Medium |
| [G08](G08-untrusted-content-envelope.md) | Untrusted external content | Retrieved or tool-returned text acting as instructions | **Start here** if you do RAG/MCP |
| [G09](G09-measurement-refusals.md) | Measurement refusals | A number quietly becoming a verdict about a person | High |
| [G10](G10-substitution-limits.md) | Substitution limits | The agent doing the work the human needed to do themselves | Domain-dependent |
| [G11](G11-certainty-and-verbatim.md) | Certainty & verbatim quoting | Confident misquotation; fabricated citations and attributions | High |
| [G12](G12-moderation-classifier.md) | Moderation classifier prompt | A classifier that follows the message it was asked to classify | High |

## How these fit together

```
                    ┌──────────────────────────────────────┐
   user input ──────►  G12 classifier  +  Tier-1 regex     │  detection: facts only
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │  policy engine (pure function)       │  meaning
                    └───────────────┬──────────────────────┘
                     redirect ◄─────┤
                                    ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  SYSTEM PROMPT — cached static block                           │
   │    G01 constitution   (rendered from the verified file)        │
   │    G02 operating rules                                         │
   │    G03 role limits                                             │
   │    G04 physical safety   G05 escalation                        │
   │    G09 measurement refusals   G10 substitution   G11 certainty │
   │    G06 tool-use discipline    G07 continuation rule            │
   └───────────────────────────┬────────────────────────────────────┘
                               ▼
                    ┌──────────────────────────────────────┐
                    │  agent loop — bounded (G06)          │
                    │  tool results: internal only         │
                    │  external results: G08 envelope      │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │  action validator — per-call caps,   │
                    │  audit, suppression (G06)            │
                    └──────────────────────────────────────┘
```

## Ordering inside the system prompt

Order matters more than people expect, and the reasoning is not aesthetic:

1. **Constitution first, always.** It must precede every persona, task, and
   user-supplied field, and it must say so in its own text. A rule that appears
   after the thing it governs reads as a footnote.
2. **Role limits before capabilities.** Describe what the agent may not be
   before you describe what it can do. Otherwise the capability list is what the
   model reasons from when the two conflict.
3. **Tool discipline adjacent to the tool schemas.** The model reads the prose
   description next to each schema more reliably than a rule 900 lines up.
4. **Language, locale, and formatting directives last**: closest to generation.

## Prompt caching

Everything in this library belongs in your **static, cacheable** prompt block.
None of it varies per turn. The point is not only cost: a cached block is
byte-identical on every round-trip of a multi-round tool loop, which is what
guarantees your non-negotiable rules govern round 3 exactly as they govern
round 1. If you rebuild the system prompt per round, verify that you rebuild it
*identically*.
