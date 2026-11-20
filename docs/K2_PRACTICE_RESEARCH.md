# K-2 practice research: what the evidence weights are consistent with

> **What this is.** The research that the K-2 practice design in
> [`K2_PRACTICE.md`](K2_PRACTICE.md) is consistent with, and the research it
> departs from, for the evidence weights recorded in
> [`docs/DECISIONS.md`](DECISIONS.md) entry 40, ruling (b). Every claim here
> names the study it rests on, states what class of evidence that study is, and
> states where it stops.
>
> **What this is not.** Not the decision, and not a source for any of its
> numbers. Entry 40 carries the rulings and their state; this document carries
> what the literature does and does not say about them. If the two disagree,
> the register is authoritative about *what was decided* and this document is
> authoritative about *what the research supports*.

---

## 1. The honest framing, before any finding

**Every number in the K-2 practice weights is a product default the owner
chose. None of them comes from research.** That covers:

- **0.5** for a Your turn answer right on the first try, unaided
  (`QUIZ_EVIDENCE_WEIGHT`);
- **0.25** for an answer right on the second try, after the move is shown
  again;
- **the half ratio** between those two;
- **0 and no ledger row** when the answer was shown or the item was left;
- **skipping the early-evidence boost** for practice answers, and **not
  counting them toward the early window**;
- **one recorded round per area per session.**

No study below tested any of these values, any ratio between them, or any rule
of this shape. The research narrows what kind of practice is worth recording
and what kind of answer is worth trusting. It cannot say how much one answer
should move an estimate. Where this document says a design choice is
"consistent with research on" something, that is the whole claim: the choice
does not contradict the finding, and the finding points the same way.

**Who read what.** The owner opened all six papers in §2 on 2026-11-16 and
recorded what each one actually says. This document's findings rest on that
reading. The independent retrieval made for this document failed: the Scite
literature tools refused every call (the account has no active plan), and the
session's network blocks `doi.org`, the publisher pages and the open
repository copies, so no paper's text could be opened from here. What could be
checked was bibliographic metadata (authors, title, journal, volume, pages and
DOI) through web search results, which is a check that each paper exists as
cited and nothing more. §2 records both results for each paper.

**Editorial notices were not checked** for any of the six papers. Retractions,
corrections and expressions of concern are what the Scite tools report, and
those tools were unavailable; the owner's reading of 2026-11-16 does not report
a notice check either. That check must be done, and its result written here,
before this document is used to close any part of entry 40.

### Evidence classes used in this document

| Class | Meaning | What it can support |
| --- | --- | --- |
| Experimental | Children assigned to practice conditions, outcomes measured | "In this setting, practice X beat condition Y" |
| Review | A summary of other studies, no new data | "The literature points this way" |
| Correlational | Measures taken together, no manipulation | "X and Y move together in this group" |
| Analytical | A model's properties derived, no children observed | "Under this model, X follows from Y" |

---

## 2. The corpus

| Study | Class | Population | Owner's reading (2026-11-16) | This document's retrieval | Editorial notices | Used for |
| --- | --- | --- | --- | --- | --- | --- |
| Káldi et al. (2025) | Experimental | Two experiments, about 100 children aged 5-6 each | Confirmed; practice beat restudy only with more initial learning and higher practice success | Metadata only; full text not opened | Not checked | Successful retrieval (§3.1), boundary condition (§6.1) |
| Fazio & Marsh (2019) | Review | Children, across studies | Confirmed nearly verbatim | Metadata only; full text not opened | Not checked | Effortful but successful retrieval (§3.1), age gap (§6.2) |
| Ophuis-Cox et al. (2023) | Experimental | 48 second graders | Confirmed | Metadata only; full text not opened | Not checked | Spaced retrieval in a classroom (§3.1) |
| Franzoi et al. (2025) | Experimental | 33 fifth graders aged 10-11 | Partly overstated in the summary; corrected in §3.2 | Metadata only; full text not opened | Not checked | Feedback until correct, older children (§3.2) |
| Veerbeek & Vogelaar (2025) | Correlational | 66 fourth and fifth graders | Overstated in the summary; corrected in §3.3 | Metadata only; full text not opened | Not checked | Prompts needed as a measure, older children (§3.3) |
| Van de Sande (2013) | Analytical | No children; a model | Partly inferred in the summary; written as an inference in §5 | Metadata only; full text not opened | Not checked | Guessing as a parameter (§5) |

**Where the summary these papers arrived with differed from the papers.** The
list of claims this research started from was a reviewer's summary, not a
reading. The owner's reading corrected three of the six:

- **Franzoi et al. (2025)** studied fifth graders, not K-2 children. The point
  that self-correction on open questions can undermine young students'
  motivation is the authors' discussion, not something the study tested. And
  spacing the sessions had no significant effect.
- **Veerbeek & Vogelaar (2025)** studied fourth and fifth graders. The number
  and kind of prompts a child needed correlated moderately to strongly with
  teachers' estimates and standardized scores taken at the same time. The study
  did not test whether prompts predict later school success.
- **Van de Sande (2013)** defines the guessing parameter and shows that right
  and wrong answers both update the estimate. That ignoring guessing inflates a
  mastery estimate is a reasonable inference from that, not the paper's words.

**Where this document's metadata check differed from the citations as
given.** Káldi et al. (2025)'s published title ends "in Preschoolers", and its
DOI is 10.1111/cdev.70018, found through search results rather than read off
the article. Van de Sande (2013) has no DOI assigned by its journal; search
results point at two different Zenodo records for it, so it is cited here by
the journal's own article page instead. Neither difference changes a finding.

---

## 3. What the design is consistent with

### 3.1 Successful, effortful retrieval for young children

The design records only a Your turn answer the child got right, and records
nothing from Watch or Together. That is consistent with research on retrieval
practice for young children, which finds the benefit tied to retrieval that
succeeds.

Káldi et al. (2025) ran two experiments with about 100 children aged 5 and 6
each. Practicing by being tested beat restudying only when the children had
more initial learning and reached higher success during practice: Cohen's
d = 0.315 for recall and 0.324 for recognition. With less initial learning
there was no meaningful effect. These are small effects, in two experiments
from one research group, with children of kindergarten age rather than of
grade 2.

Fazio & Marsh (2019), a review, put the same point in general form: retrieval
helps children most when it is effortful but successful. Being a review, it
adds no new data, and it says itself that little is known about how the effect
changes with age (§6.2).

Ophuis-Cox et al. (2023) is the closest study to Bede's own setting: 48 second
graders in ordinary classrooms, three spaced sessions of retrieval with
flashcards against restudy by chanting, on multiplication facts. Retrieval
practice gave better results 5 minutes after practice and one week later. It
is one study, about math facts rather than phonics, and its comparison is
against chanting rather than against no practice.

What this supports for Bede: a round that has the child retrieve, with Watch
and Together first so that retrieval is likely to succeed, points the same way
as this research. It does not say a recorded right answer should count 0.5.

### 3.2 Feedback until correct, in older primary students

The design never says "wrong"; after a miss it shows the move again, and after
a second miss it shows the answer. That is consistent with research on
feedback until correct, though the one study here is of older children.

Franzoi et al. (2025) studied 33 fifth graders aged 10 and 11. Testing with
accuracy feedback until every answer was correct improved learning over
rereading. Spacing the sessions further apart had no significant effect. The
suggestion that asking young students to correct their own open answers can
undermine their motivation is in the authors' discussion, not in what they
tested, and is not relied on here.

This is research on older primary students, grade 5, not K-2.

### 3.3 Assistance-adjusted measurement, in older primary students

The design records a right answer after a second showing at half the weight of
a right answer on the first try. That is consistent with research on dynamic
assessment, in which how much help a child needed is itself information,
though the one study here is of older children and does not support the size of
the step.

Veerbeek & Vogelaar (2025) gave 66 fourth and fifth graders a training test
with graduated prompts. The number and kind of prompts each child needed
correlated moderately to strongly with their teachers' estimates and with
standardized scores taken at the same time. The study did not test whether
prompts predict later learning or school success, and it says nothing about
how much less a prompted answer should count than an unprompted one.

This is research on older primary students, grades 4 and 5, not K-2.

### 3.4 Closed choices and no score shown: product rules the research does not test

A child answers by tapping one of the offered choices, or by a spoken answer
matched only to those choices, and no score, timer or streak is ever shown.
None of the six papers tests either rule. Káldi et al. (2025) measured
recognition as well as recall, which is the nearest any of them comes to a
closed-choice answer, but that was a test of what was learned, not a design
for practice. Both rules come from the product: speech recognition cannot judge
a young child's sounds ([`K2_PRACTICE.md`](K2_PRACTICE.md) §5.1), and Bede
never hurries or scores a child. They are recorded here so that nobody later
cites this document as research for them.

---

## 4. What the research cannot supply

| Product default | What the research says about it |
| --- | --- |
| 0.5 for a first-try right answer | Nothing. No study tests a weight. |
| 0.25 for a second-try right answer | Nothing. Veerbeek & Vogelaar (2025) finds help needed is informative in older children, not by how much. |
| The half ratio between them | Nothing. |
| 0 and no row when the answer was shown | Consistent with §3.1's emphasis on successful retrieval; the value itself is a product rule. |
| Skipping the early-evidence boost | Nothing. |
| Not counting toward the early window | Nothing. |
| One recorded round per area per session | Nothing. Franzoi et al. (2025) found no effect of spacing in fifth graders, which is not evidence either way about a per-session cap. |

---

## 5. The one real divergence: misses never count

**K-2 practice records only right answers.** A right answer moves the estimate
up; a miss, or an item that ended with the answer shown, records nothing. So a
practice answer can never move an estimate down.

Bayesian Knowledge Tracing works differently. Van de Sande (2013) sets out the
model: a guessing parameter, P(G), gives the chance that a child who has not
learned a skill answers right anyway, and right and wrong answers both update
the estimate. It is a reasonable inference from that model, though not the
paper's own words, that leaving guessing out of the model, and counting only
right answers, makes a mastery estimate rise faster than the child's actual
knowledge. Bede's own math estimator already treats guessing as a parameter
(`TUNED_PARAMS` in `services/diagnostic/mastery.py`, guess 0.25), so K-2
practice is the exception here, not the rule.

How large the guessing is depends on how many choices there are and whether a
wrong choice can be tapped again. For a child tapping at random:

| Choices | Wrong choice can be tapped again | Right on first try | Right within two tries | Average weight per item | Estimate reaches 0.8 in one round |
| --- | --- | --- | --- | --- | --- |
| 3 | Yes | 33% | 56% | 0.22 | 51% |
| 4 | Yes | 25% | 44% | 0.17 | 34% |
| 3 | No | 33% | 67% | 0.25 | 59% |
| 4 | No | 25% | 50% | 0.19 | 39% |

The first two columns of results are plain probability: right within two tries
is 1/3 + (2/3)(1/3) = 5/9 for three choices with re-tapping, and 1/3 + (2/3)(1/2)
= 2/3 without. The average weight uses the product defaults above. The last
column assumes a fresh estimate of 0.5, the three Your turn items of one round
all on the same domain, no early-evidence boost, and the same blend phonics
already uses (`prior + weight × (1 − prior)`), with 0.8 the threshold
`services/diagnostic/mastery.py` calls secure. Two first-try right answers
reach 0.875, and one first-try plus one second-try right answer reaches 0.8125;
three second-try right answers stop just short, at 0.79. Whether a parent then sees "secure" also depends on the early
window, which by owner ruling practice answers do not advance. These figures
are arithmetic about the product defaults, not research.

**Káldi et al. (2025) strengthens the open question rather than settling it.**
Their finding is that practice paid off only when retrieval succeeded. A right
answer reached by tapping at random is not successful retrieval, and the table
shows how often one occurs. That is an argument for open decision 40(h) in
[`docs/DECISIONS.md`](DECISIONS.md) entry 40, weak negative evidence for an
item that ended with the answer shown, since counting lucky right answers while ignoring misses works against what the research found
practice is for. It is not research for any particular value of that weight.

---

## 6. Contrary and limiting findings

### 6.1 With less initial learning, practice did nothing

Káldi et al. (2025) found no meaningful effect of practice when children had
less initial learning. The benefit appeared only once initial learning had
gone far enough for practice to succeed. Reading that onto Bede is this
document's inference, not the paper's: a round whose Watch and Together steps
have not got a child that far is giving Your turn items the child is not yet in
a position to benefit from, and its right answers are more likely to be
guesses (§5).

### 6.2 Little is known about how the effect changes with age

Fazio & Marsh (2019) say little is known about how the retrieval-practice
effect changes with age. The youngest children here are 5 and 6 (Káldi et al.,
2025); a kindergartner may be younger, and none of the studies covers the
whole K-2 range.

### 6.3 Two of the six studies are of older children

Franzoi et al. (2025) studied fifth graders and Veerbeek & Vogelaar (2025)
fourth and fifth graders. Neither says anything directly about kindergarten to
grade 2, and both are cited only as research on older primary students.

### 6.4 Spacing had no significant effect

Franzoi et al. (2025) found no significant effect of spacing. Ophuis-Cox et al.
(2023) used spaced sessions but compared retrieval against chanting, not spaced
against massed practice. Nothing here shows that a per-session cap, or a gap
between rounds, helps.

### 6.5 The comparisons are against weak alternatives

The experiments compare retrieval with restudy (Káldi et al., 2025), chanting
(Ophuis-Cox et al., 2023) or rereading (Franzoi et al., 2025). None compares
retrieval against the Watch, Together, Your turn routine as a whole, or against
no practice at all.

### 6.6 The effects are small

Káldi et al. (2025)'s effects, d = 0.315 and 0.324, are small, and appear only
in the condition with more initial learning.

---

## 7. Sources considered and not cited

- **"Individualizing Bayesian Knowledge Tracing"** (ERIC ED592687), named in
  the starting summary. Not among the six papers the owner opened, and not
  retrieved here. Not cited.
- **Web pages** on dynamic assessment, retrieval practice and speech therapy
  (CALPER, a TESOL blog, Vanderbilt guides, instructionalstrategies.org,
  cognitivepsychology.com, thespeechlife, Scribd copies, ERIC records). Not
  evidence; not cited.
- **An earlier preschool testing-effect study** that surfaced in search results
  while checking Káldi et al. (2025)'s metadata. Not retrieved; not cited.

---

## 8. Standard of evidence for this document

The same seven rules as [`PRICING_RESEARCH.md`](PRICING_RESEARCH.md) §7, and
how each was applied here.

1. **Every claim names its study.** No sentence here says research shows
   something without naming the study.
2. **Every study's evidence class is stated** (§2). One review, one analytical
   model, one correlational study and three experiments do not carry the same
   weight.
3. **Editorial notices are checked before citing, and the check is reported.**
   Not met for this version: the tools that report notices were unavailable, so
   §1 says so and §2 records "Not checked" for every paper.
4. **Nothing is cited that was not retrieved.** Each paper was opened by the
   owner on 2026-11-16. Nothing is cited on the strength of the starting
   summary or of metadata alone.
5. **Contrary findings get their own section** (§6).
6. **Weak evidence is labelled weak in the sentence that uses it**, as in
   §3.1's note that the effects are small and §3.2 and §3.3's notes that the
   children were older.
7. **The limits of each finding are stated with the finding.**

---

## References

**Fazio & Marsh (2019).** Fazio, L. K., & Marsh, E. J. (2019). Retrieval-based
learning in children. *Current Directions in Psychological Science, 28*(2),
111–116. https://doi.org/10.1177/0963721418806673

**Franzoi et al. (2025).** Franzoi, Cembrani, Mulatti, & Treccani (2025).
Retrieval practice enhances learning in real primary school settings, whether
distributed or not. *Frontiers in Psychology, 16*, 1632206.
https://doi.org/10.3389/fpsyg.2025.1632206

**Káldi et al. (2025).** Káldi, T., Szőllősi, Á., & Racsmány, M. (2025).
Multiple practice success scaffolds long-term test-enhanced learning in
preschoolers. *Child Development, 96*(6), 1934–.
https://doi.org/10.1111/cdev.70018 (also
https://academic.oup.com/chidev/article/96/6/1934/8383970)

**Ophuis-Cox et al. (2023).** Ophuis-Cox, F. H. A., Catrysse, & Camp
(2023). The effect of retrieval practice on fluently retrieving multiplication
facts in an authentic elementary school setting. *Applied Cognitive
Psychology, 37*(6), 1463–1469. https://doi.org/10.1002/acp.4141

**Van de Sande (2013).** Van de Sande, B. (2013). Properties of the Bayesian
Knowledge Tracing model. *Journal of Educational Data Mining, 5*(2), 1–10.
https://jedm.educationaldatamining.org/index.php/JEDM/article/view/35

**Veerbeek & Vogelaar (2025).** Veerbeek, J., & Vogelaar, B. (2025). Dynamic
testing of instructional needs: A training-only graduated prompts approach.
*Journal of Psychoeducational Assessment, 43*(1), 74–87.
https://doi.org/10.1177/07342829241287947
