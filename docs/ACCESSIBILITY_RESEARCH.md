# Accessibility research: how the text is presented, and how often breaks are offered

> **What this is.** The evidence base behind the reading-presentation settings
> (`letter_spacing`, `line_spacing`, `text_size`) and `frequent_break_offers`,
> and behind three things deliberately **not** built. Every claim names its
> source, states what class of evidence that source is, and states where it
> stops.
>
> **What this is not.** Not a clinical guide, and not a claim that Bede is a
> reading intervention. See §7.

---

## 1. The question, and the honest framing

A parent asked for accommodations for dyslexia and other learning differences.
The obvious build is a **dyslexia mode**. This document is largely the argument
that the obvious build is the wrong one twice over — once on principle, and
once because the single most-requested feature in it **does not work**.

**Two findings drove everything below.** The first is a defect: `learning_support`
reaches the PROMPT and nothing else, so it changes what Bede *says* and cannot
change what the screen *looks like*. A parent who typed "bigger text with more
space between the letters" got nothing. The second is §4: the evidence for
dyslexia-specific fonts is negative, and the evidence for **spacing** is good.

### Evidence classes used in this document

| Class | Meaning | What it can support |
| --- | --- | --- |
| RCT/Experimental | A controlled experiment with a comparison condition | "This manipulation changed this outcome" |
| Meta-analytic | A pooled synthesis of multiple studies | "Across studies, the effect is about this size" |
| Position | A professional body's stated position | "The field's consensus is currently this" |
| Design guidance | Convention from readability/UX practice | Weak. A default worth having, never a claim of benefit |
| Absent | Looked for and not retrieved | Nothing. Recorded so the gap is visible |

**Editorial notices were checked.** None of the studies drawn on below carries
a retraction, correction, or expression of concern. Zorzi et al. (2012) drew a
published **Letter** and a **Reply**, which is ordinary scientific exchange
rather than an editorial notice — and because it materially qualifies the
finding, it has its own section (§6.1) rather than a footnote.

---

## 2. The corpus

| Source (year) | Class | What it is used for |
| --- | --- | --- |
| Zorzi et al. (2012) | RCT/Experimental | Extra letter spacing improves dyslexic reading |
| Skottun and Skoyles (2012) | Position | The published objection to the above |
| Zorzi Reply (2012) | Position | The authors' response to that objection |
| Wery and Diliberto (2017) | RCT/Experimental | OpenDyslexic produces no improvement |
| International Dyslexia Association (2024) | Position | No reliable evidence supports dyslexia fonts |
| Katzir et al. (2013) | RCT/Experimental | Font size effects on children reverse with age |
| Liao et al. (2023) | Meta-analytic | Physical activity and attention in ADHD |
| Line-length primary source (n/a) | Absent | The "27% faster for dyslexic readers" figure — **not retrieved**; see §6.3 |

---

## 3. What was built, and on what

| Setting | Evidence | Offered to a parent as |
| --- | --- | --- |
| `letter_spacing` (carries word spacing) | **Strong** — §4.1 | An accommodation |
| `line_spacing` | **Design guidance only** — §4.3 | "Helps some readers keep their place" |
| `text_size` | **Contested; direction reverses with age** — §4.4 | A *preference*, explicitly not an accommodation |
| `frequent_break_offers` | **Not an evidence claim at all** — §5 | Removing an age limit on a parent's choice |

The table is the point. Three of the four are honest about being weak, and the
UI copy for each says so in the words a parent actually reads — because
"spacing helps and bigger text may not" is precisely the thing a parent has no
way to know, and a settings panel that presents four equal-looking controls
implies four equal claims.

---

## 4. Findings

### 4.1 Letter spacing works, and it is the strongest result here

**Zorzi et al. (2012), PNAS.** In dyslexic children aged 8-14, extra-large
interletter spacing **doubled reading accuracy** and increased reading speed by
**more than 20%**, with the effect replicating across measurement sessions,
across different reading materials, and across children reading **two different
languages (Italian and French)**. *(RCT/Experimental.)* The proposed mechanism
is **crowding** — a letter is harder to identify when close to its neighbours,
and dyslexic readers are more affected by this than typical readers.

Cross-language replication is what makes this worth building on rather than
noting: a result that survives a change of orthography is unlikely to be an
artifact of one language's spelling.

### 4.2 Dyslexia-specific fonts do not work — the most important negative here

**Wery and Diliberto (2017)** found **no improvement in reading rate or
accuracy** from OpenDyslexic, for individual students with dyslexia or for the
group. *(RCT/Experimental.)* Across studies these fonts perform no better than
Arial or Times New Roman and **sometimes worse**, and the **International
Dyslexia Association**'s position is that no reliable research evidence
supports them. *(Position.)*

This is the single most-requested "dyslexia feature" in software, and building
it would have been shipping folklore into a product whose constitution forbids
presenting unverified things as certain. **No dyslexia font is offered.**

### 4.3 Line spacing — kept, and labelled weak

No study retrieved here measures line spacing as an intervention for dyslexic
children specifically. Katzir et al. (2013) found **no effect** of line spacing
for fifth graders. What supports it is general readability guidance (line
heights around 1.3-1.5 for body text) and the practical observation that
returning to the start of the next line is where a struggling reader loses
their place. *(Design guidance.)*

**Weak, and the UI says so** — "helps some readers keep their place," never
"research shows."

### 4.4 Text size — bigger is not reliably better, and the direction reverses

**Katzir, Hershko and Halamish (2013), PLOS ONE**, titled *"Bigger Is Not
Always Better"*: for **second graders**, decreasing font size and increasing
line length both **lowered** comprehension; for **fifth graders**, decreasing
font size **raised** comprehension, with no effect of line length or line
spacing. *(RCT/Experimental.)*

A developmental reversal is a strong reason not to sell text size as an
accommodation. It is offered because a child may genuinely prefer it and
preference is reason enough — but Bede does not get to claim it helps.

---

## 5. Breaks: what the ADHD literature does and does not say

**Liao et al. (2023)**, a systematic review and meta-analysis of RCTs, found
physical activity had a **moderate effect** on attention problems in
school-aged children with ADHD. *(Meta-analytic.)* Two details matter more than
the headline:

* **Lower frequency was MORE effective** — one to two sessions per week
  produced large reductions, and interventions under three times weekly were
  most beneficial.
* **Cognitive engagement was the active ingredient**, moderating the effect
  more than environment or session length did.

**Read honestly, this does not support "offer breaks more often to help
attention."** It supports structured, cognitively engaging physical activity a
couple of times a week, which is a different thing from a pause inside a
tutoring session — and its frequency finding points the opposite way from the
intuition.

**So `frequent_break_offers` is not justified as an attention intervention, and
is not described as one.** What justifies it is narrower and does not need this
literature at all: `getSuggestedBreak` gated the optional 20-minute rhythm on
K-3, so a twelve-year-old whose parent knows they do better stopping every
twenty minutes **structurally could not have it** — not because anyone decided
against it, but because the only route in was being under nine. Removing an
arbitrary age gate on a choice that belongs to the parent is the constitution's
`authority_order`, not a clinical claim.

Stating this plainly is the point. It would have been easy, and wrong, to cite
the ADHD literature beside this setting and let a parent infer more than it
says.

---

## 6. Contrary findings

### 6.1 The published objection to letter spacing — and why it argues FOR this design

**Skottun and Skoyles (2012)** objected in PNAS that the spacing benefit may
not be dyslexia-specific: the same manipulation may help dyslexic and control
readers similarly, appearing larger for dyslexic readers only because they
start from lower performance. They also noted the control group's null result
was **underpowered** — roughly 50 controls rather than 30 would have reached
significance. *(Position.)*

**Zorzi et al. replied** that the load-bearing result was never the null in
controls but the significant **group × spacing interaction**, which showed the
benefit is significantly larger for dyslexic readers. *(Position.)*

**Take the objection seriously and it strengthens the design rather than
weakening it.** If extra spacing helps struggling readers generally rather than
dyslexic readers specifically, then offering it as a **plain setting any parent
can turn on** — rather than behind a diagnosis a family must first obtain — is
exactly the right shape. The critique argues against the dyslexia mode this
document already declined to build.

### 6.2 The strongest argument against all of this

**Presentation is the smaller half of dyslexia support.** What has the deepest
evidence base is structured, sequenced, multisensory literacy instruction —
Orton-Gillingham-derived programs — and **Bede is not that and does not become
that by adding spacing controls.** `services/diagnostic/literacy.py` measures
ten domains and `_literacy_checkin_note` is explicitly forbidden from inventing
an exercise to generate evidence.

Nothing here should read as "Bede now supports dyslexia." It supports a child
reading Bede's screen. §7 states the limit in the parent's own documentation.

### 6.3 A figure found and deliberately not used

A claim that shorter lines improve reading speed **27% for dyslexic readers**
appeared in secondary UX writing during this research. **The primary source was
not retrieved, and the figure is not cited anywhere in this document or in the
product.** Recorded so the gap is visible rather than inferred. Line length is
consequently **not** offered as a setting at all — the one number that would
have justified it is the one that could not be checked.

---

## 7. What this cannot tell you

* **No setting here was tested with a real child using Bede.** Every finding is
  transferred from reading research on other materials. Whether letter spacing
  helps a child read *this* interface is unmeasured.
* **The values are judgements, not derived quantities.** Zorzi's manipulation
  was expressed in typographic points on printed material; `wide` (0.06em) and
  `wider` (0.12em) are proportional analogues chosen to bracket a similar
  range, not a reproduction of the study's stimulus.
* **Bede is a tutor.** Not special education, not therapy, not a reading
  intervention, and not a substitute for a structured literacy program, speech
  therapy, or occupational therapy. `docs/PARENT_SETUP.md` says this to parents
  in their own words, which matters more than saying it here.
* **Nothing here is a diagnosis, and no setting names a condition.** Deciding a
  child needs support is a judgement for a qualified evaluator or the parent
  who lives with them — the constitution's `authority_order`.

---

## 8. The rules this document holds itself to

Per `CLAUDE.md`'s standing workflow, restated so the document is checkable:

1. Every claim names its source. No bare "research shows".
2. Every source states its evidence class, from the closed vocabulary in §1.
3. Editorial notices are reported, whether or not anything was found.
4. Nothing is cited that was not retrieved — see §6.3, where a figure was found
   and deliberately not used.
5. Contrary findings get their own section (§6), not a subordinate clause.
6. Weak evidence is labelled weak in the sentence that uses it (§4.3, §4.4).
7. The limits of each finding are stated with the finding (§7).

---

## References

**International Dyslexia Association (2024).** *Do Special Fonts Help People
with Dyslexia?* https://dyslexiaida.org/do-special-fonts-help-people-with-dyslexia/

**Katzir et al. (2013).** Katzir, T., Hershko, S., & Halamish, V. *The Effect
of Font Size on Reading Comprehension on Second and Fifth Grade Children:
Bigger Is Not Always Better.* PLOS ONE.
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0074061

**Liao et al. (2023).** *Effect of physical activity on attention in school-age
children with ADHD: a systematic review and meta-analysis of randomized
controlled trials.* Frontiers in Physiology.
https://pmc.ncbi.nlm.nih.gov/articles/PMC10415683/

**Line-length primary source (n/a).** The "27% faster for dyslexic readers"
line-length figure. **Not retrieved**, and therefore not cited — see §6.3.

**Skottun and Skoyles (2012).** *Interletter spacing and dyslexia.* PNAS
Letter. https://pmc.ncbi.nlm.nih.gov/articles/PMC3497831/

**Wery and Diliberto (2017).** *The effect of a specialized dyslexia font,
OpenDyslexic, on reading rate and accuracy.* Annals of Dyslexia.
https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5629233/

**Zorzi et al. (2012).** Zorzi, M., Barbiero, C., Facoetti, A., Ziegler, J. C.,
et al. *Extra-large letter spacing improves reading in dyslexia.* PNAS.
https://www.pnas.org/doi/10.1073/pnas.1205566109

**Zorzi Reply (2012).** *Reply to Skottun and Skoyles: Statistical and
practical significance of extra-wide letter spacing for dyslexic children.*
PNAS. https://www.pnas.org/doi/10.1073/pnas.1213265109
