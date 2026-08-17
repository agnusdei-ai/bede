# G11 — Certainty and Verbatim Quoting

## What it prevents

Confident wrongness in the specific places where the person cannot check.

Ordinary hallucination is widely discussed. This file is about three narrower
failures that persist in otherwise well-built systems, because in each one the
model's output is *fluent, plausible, and unverifiable by the person reading
it*.

**Misquotation of texts that must be exact.** Scripture, statute, licensed
standards, contract language, a company policy, a poem. A model reproducing a
long passage from memory will get most of it right and subtly alter some of it,
and a subtle alteration is worse than a refusal because it carries the authority
of a quotation. Bede's answer is a **verbatim catalog**: pre-reviewed texts
stored as data, with a prompt instruction to quote the provided text exactly and
never to compose or paraphrase one. An earlier design had the agent "freshly
adapt" a prayer each day — a model improvising devotional wording daily, with no
human ever reviewing the actual words. That was removed, and the rule is now
uniform: select and quote, never invent.

**The pleasant, universally repeated, false attribution.** Bede teaches *ora et
labora* and states plainly that the motto appears nowhere in the Rule of St.
Benedict — it is a 19th-century coinage — and supplies a genuine line from the
Rule to quote instead. Every field has these. A model will reproduce the folklore
version confidently, because its training data is mostly people repeating it.
When you find one in your domain, encode the correction rather than relying on
the model to know better.

**Presenting a recollection as a verified copy.** Bede supports several
copyrighted translations of Scripture. Research into each publisher's actual
stated permissions found the limits generous — far beyond anything one response
would approach — so licensing turned out not to be the binding constraint. The
binding constraint was accuracy: the system holds no verified licensed copy of
those texts to check its own memory against, so it *cannot guarantee* its
recollection of a specific edition's exact wording. The resulting instruction is
to paraphrase by default, keep direct quotation to a line or two it is genuinely
confident about, always cite chapter and verse so the family can check, and
never present uncertain wording as though it were that edition's precise text.
Note that the honest reason and the assumed reason were different, and that
finding out required actually looking.

## The block

```text
<certainty>
Never fabricate certainty, evidence, a source, a quotation, or authority you do
not have.

When you quote {TEXTS THAT MUST BE EXACT}, use only text provided to you in this
prompt, exactly as written. You do not compose, paraphrase, adapt, modernize, or
reconstruct one from memory, however brief or well-intentioned. If no text was
provided for what is being asked, say so and offer to work with what you do have.

For {TEXTS YOU MAY NOT HAVE A VERIFIED COPY OF}: paraphrase by default. Keep any
direct quotation to a line or two you are genuinely confident about, always cite
the reference precisely so the person can check it themselves, and never present
uncertain wording as though it were the exact text. This does not mean thinning
out the substance — narrate the content fully and ask real questions; only
literal wording needs this care.

When you are uncertain, say which part you are uncertain about, rather than
hedging the whole answer or presenting all of it evenly. "I am confident about
X; I would check Y before relying on it" is more useful than either.

If a widely repeated attribution is wrong, say so plainly and give the correct
source. Repeating a pleasant falsehood because it is commonly repeated is a
failure of this rule.
</certainty>
```

## Adaptation notes

**Identify your must-be-exact texts and stop generating them.** This is a data
problem masquerading as a prompt problem. Store the canonical text, render it
into context, instruct the model to reproduce it exactly, and test that the
stored copy matches the source. Prompting alone will not get you there.

**"Do not thin out the substance" needs to be explicit.** The predictable
overcorrection to a quoting restriction is an agent that becomes vague about the
whole subject. State that the restriction covers literal wording only.

**Cite the reference even when paraphrasing.** A precise citation attached to a
paraphrase is what converts an unverifiable claim into a checkable one, and it
costs nothing.

**Record what you actually verified, and when.** Bede's Latin catalog states in
its own header that every text was checked against published editions at
authoring time, and that a sibling catalog's texts originally came from model
knowledge because a reference source was not reachable during that build — later
partially cross-checked. That is uncomfortable to write down and it is the only
way a later reader can tell which content has been verified. A document that
does not say it looked has not looked, as far as anyone else can tell.

## How to test it

- **Data-integrity tests on the catalog.** Every entry has its required fields,
  a citation, and a source. Fail CI on a missing one.
- **A test that the stored text is what is rendered** — no truncation, no
  smart-quote mangling, no template interpolation in the middle of a quotation.
- **A test that the "quote only what is provided" instruction is present**
  whenever a catalog block is rendered.
- **Behavioral spot-check for the known misattributions.** A small evaluation
  set of the folklore claims in your domain. This one genuinely needs a live
  model, and it is worth running when you change models — the failure is
  model-specific and moves between versions.
