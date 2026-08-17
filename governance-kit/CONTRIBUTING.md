# Contributing

## The bar

**A pattern gets in if it prevented a real failure, and you can state the
failure.**

That is the whole bar, and it is deliberately hard to clear. Patterns that sound
prudent but have never caught anything make a checklist longer and an engineer
less likely to finish reading it. Every item here costs the attention of everyone
who adopts the kit, so the question is not "is this a good idea" but "is this
worth the attention it will consume."

If you have a pattern you believe in but have not yet seen fail, open an issue
rather than a pull request. It may well be right; it just needs someone to hit
it first.

## What a good contribution looks like

For a **new prompt block** (`prompts/GNN-name.md`), follow the existing four
sections:

1. **What it prevents**: the concrete failure, with the sequence of events.
   Not a category name. "Prompt injection" is a category; "a summarizer wrote a
   sentence from a conversation the user steered and replayed it into every
   future session" is a failure.
2. **The block**: drop-in text with `{PLACEHOLDERS}`. It must work for someone
   whose domain is nothing like yours.
3. **Adaptation notes**: what to change, and specifically **what not to
   change** and why. The load-bearing clause is usually the one that reads as
   redundant.
4. **How to test it**: including how to verify the test by breaking the thing
   it guards.

For **reference code**, no third-party dependencies. Standard library only.
These modules must be importable from anywhere in a process, including code that
runs before a framework is initialized. That is what lets the constitution
loader verify at import time.

For a **fix**, say in the PR body that you verified it by reintroducing the
defect, and what happened.

## Style

The prose here is dense on purpose. It is written for an engineer deciding
whether to adopt a control, who needs the reasoning to make that decision.
Specifically:

- **State the trade-off.** Every control costs something. A section that reads
  as pure upside has left something out, and the reader will find it later at a
  worse moment.
- **State the limits in the artifact.** If a control is guidance rather than a
  guarantee, say so in the file, not in a footnote.
- **Prefer the specific over the general.** "Sanitize user input" is advice
  nobody can act on. "Sanitize anything you replay into prompt context, on both
  the write and read paths, because rows written before the fix are still live"
  is a change someone can make on Tuesday.
- **No marketing.** Nothing here is comprehensive, complete, or
  enterprise-grade.

## Scope

**In scope:** governance prompts, enforcement patterns, threat-model structure,
testing discipline for controls, and framework mappings used as gap-finding
tools.

**Out of scope:** anything domain-specific enough that most adopters would strip
it; general application security well covered elsewhere (authentication,
encryption, container hardening); model evaluation harnesses; anything requiring
a dependency.

## Reporting a security issue

If you find a vulnerability in the reference code, or a bypass in a pattern
here, do not open a public issue. Email **security@agnusdei.ai**.

A bypass in a documented pattern is genuinely valuable: the patterns claim to
prevent specific failures, and a demonstration that one does not is exactly the
kind of correction this kit is built to absorb. It will be credited unless you
prefer otherwise.

## License

Contributions are accepted under Apache License 2.0, matching the kit. By
opening a pull request you confirm you have the right to license the
contribution under those terms.
