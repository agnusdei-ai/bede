# Locale research: choosing a third language

> **What this is.** The evidence base behind [docs/DECISIONS.md](DECISIONS.md)
> entry 22 — which language Bede should support after `en` and `es`, given that
> entry 19 commits the developing-market deployment to hardware in the room.
> Every claim names its source, states what class of evidence that source is,
> and states where it stops.
>
> **What this is not.** Not the decision. The register carries state; this
> document carries the argument.

---

## 1. The honest framing, before any finding

**Three questions were run together and have different answers.** "Which
language do the most people who need Bede speak", "which language can Bede
actually be good in", and "which language opens a market Bede's current
architecture can serve" pick out three different candidates. Most of the work
below is separating them.

**The result is not the obvious one.** The Philippines prompted this question,
and the finding is that a Filipino locale would not unlock the Philippines —
because English is a legally mandated medium of instruction there
(§4.1). Meanwhile the language with by far the largest unmet need reaches a
market Bede structurally cannot serve today (§6.2), and the language with the
largest Catholic population reaches one that is currently illegal (§4.3).

**A locale here is not a translation job.** `homeschool-tutor`'s UI is 498
strings and already fully mirrored for `es`. The expensive part is content:
`services/poetry_catalog.py`, `latin_catalog.py`, `greek_catalog.py` and
`logic_catalog.py` carry **no locale awareness at all**, and
`prayer_catalog.py`'s Spanish exists only because real Spanish prayer texts
were sourced by hand. The verbatim discipline — Bede quotes pre-reviewed
devotional text and never composes it — means a new locale needs *sourced,
human-reviewed content*, not machine translation. `models/schemas.py`'s
`BIBLE_TRANSLATIONS` is likewise eleven English editions and nothing else.

### Evidence classes used in this document

| Class | Meaning | What it can support |
| --- | --- | --- |
| Legal | A statute, regulation, or court ruling | "This is or is not permitted" |
| Institutional | Statistics published by the body that collects them | "This many, as counted by the counter" |
| Empirical | Observed measurement, estimated | "In this population, X was the case" |
| Documentary | Vendor or project documentation | "This is what the maker claims" |
| Absent | Looked for and not retrieved | Nothing. Recorded so the gap is visible |

**Editorial notices were checked** where a source is a published study: none of
the empirical sources drawn on below carries a retraction, correction, or
expression of concern. The legal and institutional sources are primary
documents, for which the equivalent check is whether they have been superseded
— stated per source in §2.

---

## 2. The corpus

| Source (year) | Class | What it is used for |
| --- | --- | --- |
| Republic Act 12027 (2024) | Legal | Philippine medium of instruction reverts to Filipino and English |
| DepEd Order 001 (2022) | Legal | Philippine homeschooling runs through accredited providers |
| STF RE 1492951 (2025) | Legal | Homeschooling is not lawfully exercisable in Brazil absent federal law |
| UNCTAD LDC list (2025) | Institutional | Which candidate markets are UN-designated least developed countries |
| Vatican Statistics Office (2025) | Institutional | Catholic population by country |
| World Bank (2021) | Empirical | Learning poverty and language of instruction |
| AIR KIX DRC (2024) | Empirical | Bilingual instruction outcomes in the Democratic Republic of the Congo |
| Encyclopedia (2000) | Institutional | Catholic share of DRC primary education |
| OpenAI Whisper (2022) | Documentary | Model sizes; that per-language accuracy varies widely |
| Whisper Appendix D (2022) | Absent | The per-language WER table — **not retrieved**; see §5.1 |
| Meta Llama 3.3 (2024) | Documentary | Eight officially supported languages |
| Google Gemma 3 (2025) | Documentary | 140 languages claimed |
| Alibaba Qwen 3.5 (2026) | Documentary | 201 languages claimed |

---

## 3. What actually constrains the choice

Bede's locale question is unusually over-determined. Five things must hold at
once, and each rules out candidates the others do not:

1. **A locally-runnable model must be good in it.** Entry 19 commits to
   on-premises inference on donated hardware, so "GPT-class multilingual
   quality" is not available. The constraint is what a 7-30B open-weight model
   does, which is not what a frontier model does.
2. **Whisper must transcribe children speaking it.** Voice is not an
   accessory here — narration is the central pedagogical act, and voice
   biometrics gate the session.
3. **Sourced public-domain devotional and poetic content must exist.** The
   verbatim discipline forbids the model composing it.
4. **A Christian classical education market must exist.**
5. **Bede's current architecture must be able to serve that market.** One
   family, one parent credential, up to ten students.

Constraint 5 is the one that decides this, and it was not on the list when the
question was asked.

---

## 4. Findings by candidate

### 4.1 Filipino — ruled out, and with a citable reason

**Republic Act 12027 (October 2024) discontinued mother-tongue-based
instruction for Kindergarten to Grade 3**, reverting the medium of instruction
to **Filipino and English**, with regional languages as auxiliary media, from
school year 2025-2026. *(Legal.)*

That is decisive. English is not merely widely spoken in Philippine education —
it is one of two legally mandated media of instruction. **Bede in English is
already curriculum-aligned in the market that prompted this question.** A
Filipino locale would be a comfort improvement for younger children, not an
unlock, and it would compete for effort with the content work in §1 that any
locale requires.

Separately: **DepEd Order No. 001, s. 2022** makes homeschooling an Alternative
Delivery Mode requiring enrolment through a DepEd-accredited provider.
*(Legal.)* This confirms, from the regulation rather than from general
knowledge, the claim flagged as unverified in entry 21 — the Philippine
deployment is provider-mediated.

### 4.2 French — the largest need, by a wide margin

* The **Democratic Republic of the Congo has roughly 55 million Catholics**,
  the largest Catholic population in Africa and fifth in the world.
  *(Institutional, Vatican Statistics Office.)*
* It is a **UN-designated least developed country**, as are Madagascar and
  Haiti — the only LDC in the Americas. *(Institutional, UNCTAD.)*
* The Catholic Church is **the dominant actor in Congolese education**: its
  schools educated over 60% of primary and over 40% of secondary students
  through the 20th century, and roughly 38% of religious-network public schools
  are Catholic, against about 80% of sampled public primaries being
  religious-network managed at all. *(Institutional / Empirical.)*
* French is among the best-supported languages in every relevant tool. It is
  one of the **eight languages Llama 3.3 officially supports**, and is covered
  by Gemma 3's claimed 140 and Qwen 3.5's claimed 201. *(Documentary — see
  §5.2 on how little that claim is worth.)*
* Public-domain French Catholic literature is vast, and public-domain French
  Scripture exists (Crampon; Segond 1910), which constraint 3 requires.

### 4.3 Portuguese — largest Catholic population, legally frozen market

* **Brazil has about 140 million Catholics, the largest of any country.**
  *(Institutional.)*
* **But homeschooling is not lawfully exercisable there.** In *RE 1492951*
  (First Panel, concluded 28 March 2025) the Supreme Federal Court upheld the
  unconstitutionality of a district law instituting homeschooling, holding that
  the duty to enrol children in regular schools cannot be substituted by home
  education absent federal regulation, and has struck down state-level
  authorisations. PL 1338/2022 is pending in the Senate. *(Legal.)*
* Mozambique and Timor-Leste are Portuguese-official LDCs; Timor-Leste is
  overwhelmingly Catholic but has a population near 1.4 million, and Tetum is
  the everyday language.

Portuguese therefore has the largest addressable population and, right now, no
lawful family market in the country that supplies almost all of it.

---

## 5. What the evidence could not establish

Stated as its own section because a gap that is not written down reads as an
absence of risk.

### 5.1 Whisper's per-language accuracy — not retrieved

The Whisper repository states that performance "varies widely depending on the
language" and directs readers to Appendix D of the paper for the per-language
WER table. **That appendix was not retrieved, and no per-language accuracy
figure is asserted anywhere in this document.** A secondary source reporting
roughly 10% average WER across FLEURS for `large-v3` was found and is
deliberately **not** cited: it was not verified against the primary table, and
rule 4 of this repository's research standard forbids citing what was not read.

What *is* established, and matters more: Whisper ships at tiny (39M), base
(74M), small (244M), medium (769M) and large (1.55B) parameters, and larger
models are materially better on non-English audio. *(Documentary.)*
`core/config.py` sets **`whisper_model_size: "base"` — 74M, the second
smallest.** That default was chosen for an English-speaking, CPU-constrained
deployment, and **this project has never measured its accuracy on children
speaking any non-English language.** On a CPU-only LDC box (Tier A of
`docs/LDC_DEPLOYMENT.md`) it also cannot casually be raised, because Whisper
competes with the language model for the same cores.

**This is a blocking unknown for any third locale, including `es` as already
shipped**, and it is cheap to resolve: transcribe recordings of children in the
target language at `base` and `small` and compare. It is recorded in entry 22
rather than assumed away.

### 5.2 "Supports N languages" is a claim about training, not quality

Gemma 3 claims 140 languages and Qwen 3.5 claims 201, against Llama 3.3's
eight. *(Documentary.)* These numbers are **weak evidence and should be
treated as weak**: they are vendor claims about training coverage, not
measurements of instruction-following, tool-calling, or doctrinal care at the
7-30B sizes entry 19's hardware permits. Bede's own requirement — eleven tools
with required fields, a ~16k-token constitution-bearing system prompt, and a
fail-open moderation classifier running on every turn — is not what any of
these numbers measures. Entry 20 already records that the model evaluation has
not been done; a third locale multiplies it rather than inheriting it.

---

## 6. Contrary findings

Given their own section, per this repository's research standard, because a
corpus assembled to support a conclusion is not evidence.

### 6.1 French Africa is the hardest possible case for a language-mediated tutor

This is the strongest argument against §4.2 and it is not a footnote.

**About 80% of 10-year-olds in Western and Central Africa cannot read and
understand a simple text.** In Sub-Saharan Africa roughly **90% of students are
taught in a language other than the one they speak at home**, and a non-native
speaker may begin school with **50 words or fewer** of the language of
instruction against 5,000-7,000 for a native speaker. *(Empirical, World
Bank.)* Research in the DRC specifically found that local-language instruction
improved comprehension and *eased the transition to French*, with L1 decoding
skill correlating with L2 reading. *(Empirical, AIR/GPE KIX.)*

Bede is Socratic dialogue and narration — **the most language-dependent
teaching method there is.** A French Bede in Kinshasa would be conducting
subtle back-and-forth questioning in a language a substantial share of its
students hold weakly. The product would be worst exactly where the need is
greatest.

This does not rule French out. It does mean French cannot be shipped as a
straight locale port: it needs the ability to scaffold in a home language, which
is a larger feature than a locale and is not designed.

### 6.2 The blocker is not language at all

Both leading candidates reach their markets through **institutions** — Catholic
schools and parishes in the DRC, DepEd-accredited providers in the Philippines,
and, if Brazil ever legalises, most likely schools there too. Bede today assumes
one family administering its own pod: a single `PARENT_PASSWORD`, one
`CHILD_PIN`, one licence.

That is **entry 21, which is `deferred`.** So no third locale unlocks anything
in a developing market until entry 21 is resolved — and entry 21's own warning
applies with full force here: a multi-family deployment is not reachable by
adding students to one pod, because one shared parent credential across
unrelated families puts each family's records in reach of the others.

**The honest ordering that follows: entry 21 before any locale.** A translated
Bede that cannot lawfully or safely be deployed to the institutions that would
run it is effort spent ahead of the thing blocking it.

### 6.3 The first LDC deployment needs no third locale

Entry 19 names the Philippines first. §4.1 shows English is a mandated medium
of instruction there. **The third locale is therefore a second-market decision,
not a prerequisite for the LDC programme**, which removes the urgency this
question was asked with.

---

## 7. The recommendation

**French**, as the third locale, staged and conditioned — not started now.

It is the only candidate where the need is largest, the deployment thesis
matches (on-premises hardware, no reliable connectivity, LDC status across DRC,
Madagascar and Haiti), the model and speech tooling are strong, and public-domain
devotional content in the required shape exists.

It should be started only after three things, in this order:

1. **Entry 21 resolved** (§6.2). Without institutional administration, French
   reaches almost none of the population that motivates it.
2. **Entry 20's model evaluation done**, extended to French, plus §5.1's
   Whisper measurement. Both are cheap relative to a locale port and both can
   invalidate it.
3. **A named content collaborator** for the verbatim catalogs — a French-speaking
   Catholic educator who will source and review prayer, poetry and Scripture
   selections. `docs/LOCALIZATION.md` already states that shipped locales are
   AI-drafted first passes needing native review before being a real family's
   primary experience; for devotional content in a market this document is
   arguing is underserved, that review is a precondition rather than a
   follow-up.

**Portuguese is the runner-up and its blocker may lift on its own**, which
makes it a deferral against a named trigger rather than a rejection: if PL
1338/2022 passes, Brazil becomes the largest Catholic family-homeschool market
in the world overnight, with better model and speech support than French and no
§6.1 problem.

**Filipino is rejected** on RA 12027, with the reason recorded so it is not
re-proposed.

---

## 8. What this cannot tell you

* **Nothing here measures demand.** Catholic population is not homeschool
  demand, and homeschool legality is not homeschool appetite. The instrument
  that would measure it is `docs/BETA_SURVEY.md`, which asks nothing about
  language or market. Adding a locale question to the educator survey is the
  cheapest next step in this whole document.
* **No candidate was evaluated by running Bede in it.** Every quality claim
  here is documentary.
* **Legal status changes.** RA 12027 is a year old; the Brazilian Senate is
  actively considering PL 1338/2022; UNCTAD reviews the LDC list every three
  years and Senegal is scheduled to graduate in 2029. Re-check before acting.
* **This document has no economist, lawyer, or native speaker behind it.** It
  is desk research by an agent, and the legal findings in particular deserve
  confirmation by someone qualified in each jurisdiction before money moves.

---

## 9. The rules this document holds itself to

Per `CLAUDE.md`'s standing workflow, restated so the document is checkable
against them:

1. Every claim names its source. No bare "research shows".
2. Every source states its evidence class, from the closed vocabulary in §1.
3. Editorial or supersession status is reported, whether or not it found
   anything.
4. Nothing is cited that was not retrieved — see §5.1, where a figure was found
   and deliberately not used.
5. Contrary findings get their own section (§6), not a subordinate clause.
6. Weak evidence is labelled weak in the sentence that uses it (§5.2).
7. The limits of each finding are stated with the finding (§8).

---

## References

Every source is given with a stable link, because a claim a reader cannot check
is not evidence.

**Alibaba Qwen 3.5 (2026).** Qwen 3.5 model documentation — claimed language coverage.
https://arxiv.org/abs/2505.09388 *(Qwen3 technical report; the 3.5 coverage
figure is from vendor documentation and is treated as such.)*

**AIR KIX DRC (2024).** *Strengthening Bilingual and Multilingual Learning Systems in
the Democratic Republic of the Congo.* GPE KIX.
https://www.gpekix.org/sites/default/files/2025-05/KIX-Strengthening-Bilingual-Education-DRC.pdf

**DepEd Order 001 (2022).** *DepEd Order No. 001, s. 2022* — homeschooling as an
Alternative Delivery Mode. https://www.depedncr.com.ph/homeschooling/

**Encyclopedia (2000).** *The Catholic Church in the Democratic Republic of the
Congo* — historical share of primary and secondary enrolment.
https://www.encyclopedia.com/religion/encyclopedias-almanacs-transcripts-and-maps/congo-democratic-republic-catholic-church

**Google Gemma 3 (2025).** Gemma 3 model documentation — claimed language coverage.
https://ai.google.dev/gemma/docs/core

**Meta Llama 3.3 (2024).** Llama 3.3 model card — eight officially supported languages.
https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/MODEL_CARD.md

**OpenAI Whisper (2022).** *Robust Speech Recognition via Large-Scale Weak
Supervision* — Whisper model sizes and the statement that per-language accuracy
varies widely. https://arxiv.org/abs/2212.04356 and
https://github.com/openai/whisper

**Republic Act 12027 (2024).** *Republic Act No. 12027* — discontinuing the mother tongue
as medium of instruction for Kindergarten to Grade 3.
https://edcom2.gov.ph/senate-oks-discontinuation-of-mother-tongue-as-medium-of-instruction-from-kinder-to-grade-3/

**STF RE 1492951 (2025).** *Recurso Extraordinário 1492951*, First Panel, concluded 28
March 2025 — homeschooling unconstitutional absent federal regulation.
https://buscadordizerodireito.com.br/jurisprudencia/5999/nao-e-possivel-atualmente-o-homeschooling-no-brasil

**UNCTAD LDC list (2025).** *UN list of least developed countries.*
https://unctad.org/topic/least-developed-countries/list

**Vatican Statistics Office (2025).** *Pontifical Yearbook 2025 / Annuarium Statisticum
Ecclesiae* — Catholic population by country and region.
https://www.vaticannews.va/en/vatican-city/news/2025-03/pontifical-yearbook-2025-priests-religious-statistics.html

**Whisper Appendix D (2022).** Appendix D.1/D.2/D.4 of the Whisper paper — the
per-language WER/CER tables. **Not retrieved.** Recorded here so its absence is
visible rather than inferred. https://arxiv.org/abs/2212.04356

**World Bank (2021).** *Teaching young children in the language they speak at
home is essential to eliminate Learning Poverty.*
https://www.worldbank.org/en/news/press-release/2021/07/14/teaching-young-children-in-the-language-they-speak-at-home-is-essential-to-eliminate-learning-poverty
