# Beta surveys: parents and co-op educators

Two survey instruments for the beta period, plus the reasoning behind
every question and the rules that govern what we are allowed to ask.

This file is the **source of truth**. The same questions are delivered
three ways, and all three must agree with what is written here:

| Channel | Audience | Where |
| --- | --- | --- |
| Hosted form (primary) | Beta parents | `site/survey/index.html` → `https://agnusdei.ai/survey/` |
| Hosted form (primary) | Co-op educators | `site/educators/index.html` → `https://agnusdei.ai/educators/` |
| In-app prompt | Beta parents already using Bede | `homeschool-tutor/src/components/BetaSurveyModal.tsx` |
| Email / in person | Either | Copy the question bank out of this file |

All three land in the same operator inbox through the same pipeline
(`POST /feedback` → Resend → `FEEDBACK_EMAIL`), and nothing any of them
collects is persisted server-side beyond that one outbound email. See
`homeschool-api/routers/feedback.py`.

If you change a question, change it here first, then in the page or the
component. A question that exists in one channel and not another produces
answers that cannot be pooled.

---

## What this beta is deciding

Three decisions, chosen deliberately over the many others we could ask
about. Every question below earns its slot by feeding one of them. A
survey that asks everything answers nothing.

1. **Does the pedagogy land.** Bede asks rather than tells, runs on
   narration, and defers to the parent. That is a conviction, not a
   measured result. We have no study of Bede and say so publicly
   (`site/faq/index.html`). The beta is the first time it meets children
   who are not ours.
2. **Pricing and packaging.** There is no published price, and the
   licensing tiers in `homeschool-api/core/licensing.py` do not yet have
   a co-op shape. We need a real range and a real unit (per child, per
   family, per co-op) before we set one.
3. **Are co-ops a real channel.** A co-op leader who recommends Bede
   reaches thirty families in one conversation. We do not know whether
   they would, what would stop them, or who in a co-op even decides. The
   word "co-op" appears twice in this entire repository, both times in
   passing. That is the size of the gap.

What we are **not** surveying for, and why:

- **Bug and friction triage.** Already covered by
  `site/feedback/index.html` ("Tell us what to fix") and the in-session
  `FeedbackModal`. Folding it in here would double the length of both
  instruments for information we already have a channel for. Both survey
  pages link to the feedback form for exactly this.
- **Anything about a child's faith.** Never measured, never scored,
  never asked about as an outcome. See `docs/CONSTITUTION.md` and
  CLAUDE.md's standing rule. We may ask a parent whether the faith
  *modules* fit their tradition, which is a question about our software.
  We may not ask how their child is doing spiritually, which is not our
  business.

---

## Rules for these instruments

These are not style preferences. Each one exists because the obvious
version of the question would have been wrong.

1. **Never ask a parent to rate their child.** Not reading level, not
   attentiveness, not maturity, not "how is your child doing." Ask about
   *Bede* and about the *parent's own experience*. This is the same
   distinction the product itself draws between `SkillActivityLog` (an
   event) and `MasteryProfile` (a claim about a child), and between
   scoring the work product and scoring the person
   (`_WORK_SCORING_NOTE`). A survey is not exempt from a rule the
   software follows.
2. **Anonymous by default.** Name and email are the last two fields and
   both are optional. A form with two boxes filled in is worth more than
   one nobody finishes.
3. **Never collect anything about a specific child.** No names, no ages
   tied to a name, no free text invited about an individual child's
   difficulties. Grade *bands* only.
4. **Ask what happened, not what they predict they would do.** "How many
   days did you actually use it" beats "would you use it." The one
   deliberate exception is pricing, where a stated intention is the only
   instrument available before a price exists.
5. **Anchor price before asking for one.** What a family already spends
   is the frame; a number produced without it is noise.
6. **Let them say it did not work.** Every scale has an honest bad end,
   and "we stopped using it" is an offered answer on both forms. A
   survey only beta enthusiasts can complete tells you nothing you did
   not already believe.
7. **No incentives.** A gift card buys completions from people who want
   the gift card. We would rather have thirty honest responses than two
   hundred bought ones.

---

## Instrument A: beta parents

Roughly five minutes. Sections in this order, because grounding comes
first, pedagogy is what they will be freshest on, and price is the
question most likely to make someone abandon a form partway through.

### A1. Grounding

**1. How many school days has your child actually used Bede?**
`Fewer than 3` · `About a week` · `Two to four weeks` · `More than a month` · `We stopped using it`

> Every other answer means something different depending on this one.
> "It is wonderful" from three sessions is a first impression; from six
> weeks it is a finding. The last option is the important one and is
> deliberately not hidden behind a skip.

**2. If you stopped, what stopped you?** *(free text, shown to everyone)*

> Asked of everyone rather than branched, because a family still using
> it can name the thing that nearly made them quit.

**3. Which grade bands are you teaching?** `K-2` · `3-5` · `6-8` · `Older`

**4. How many children are using it?** `1` · `2` · `3` · `4 or more`

> Feeds packaging directly. If most beta families run three or four
> children, per-child pricing is the wrong unit whatever the number.

### A2. Does the pedagogy land

**5. What happened to your own teaching time?**
`Gave me real time back` · `About the same` · `Cost me time` · `Too early to say`

> The honest value proposition for a homeschooling parent is hours, not
> engagement. If Bede costs a parent time, nothing else on this form
> matters.

**6. When your child narrates to Bede, what Bede does with it is:**
`Better than I would have done` · `About what I would have done` · `Worse than I would have done` · `Have not watched closely enough`

> The sharpest pedagogy question available, because it compares Bede to
> the real alternative, which is the parent. A tutor that is merely good
> is not obviously worth having.

**7. Has Bede ever said something you had to correct?**
`No` · `Yes, small` · `Yes, something that mattered` — plus **What was it?** *(free text)*

> Accuracy is a constitutional commitment, not a quality metric
> (`docs/CONSTITUTION.md`'s never-fabricate rule). One credible report
> here outranks every satisfaction score on the page, and this is the
> only way we find out.

**8. Does your child go back to it willingly?**
`Asks for it` · `Goes without complaint` · `Has to be told` · `Resists it`

> Phrased as an observation of behavior, not a rating of the child. What
> a child does is a fact; what a child is like is not ours to score.

**9. How is the Socratic questioning landing?**
`About right` · `Too hard, frustrating` · `Too easy` · `Too many questions` · `Not enough to judge`

> Mirrors `site/feedback/index.html` verbatim so the two can be pooled.

**10. Which one subject is doing the most work for you?** *(single select from the subject list)*

**11. Which would you turn off tomorrow?** *(single select, plus "none")*

> Together these do what "rate each subject 1-5" does, in two questions
> instead of fourteen, and they force a real choice.

**12. Does the Progress page tell you anything you did not already know?**
`Yes, regularly` · `Once or twice` · `No` · `Have not opened it`

> Progress reporting is expensive to build and easy to convince
> ourselves matters. "Have not opened it" is a real answer and we want
> to know how often it is the true one.

**13. Do the faith modules fit your family?**
`Fits well` · `Close, not quite` · `Does not fit our tradition` · `We do not use them`

> A question about our software's shape, not about the family's faith.
> Scripture & Bible Study and Saints & Catechism are separate subjects
> on purpose; this is how we learn whether that split is right.

### A3. Pricing and packaging

**14. What do you currently spend per year on the things Bede would
replace or reduce?** *(curriculum, tutoring, subscriptions)*
`Under $200` · `$200-500` · `$500-1,000` · `$1,000-2,500` · `More than $2,500`

> The anchor. Asked before any price question, never after.

**15. If Bede stopped working tomorrow, what would you do instead?** *(free text)*

> Revealed preference. The named substitute is the real competitor, and
> it is usually not another AI tutor.

**16-19. Price sensitivity, for your whole family per month:**
- At what price would it be **so cheap you would question the quality**?
- At what price is it a **bargain**?
- At what price does it start to feel **expensive but still worth it**?
- At what price would you **not buy it at all**?

> The standard four-question price-sensitivity block. Four short numeric
> answers give a defensible acceptable range; one "what would you pay"
> gives a number that is almost always low and unusable.

**20. Which shape fits your family best?**
`Per child, per month` · `One flat family price` · `One-time purchase, self-hosted` · `Through our co-op` · `No opinion`

**21. Would you rather run it yourself or have us host it?**
`Run it on our own computer` · `You host it` · `Whichever is cheaper` · `Do not know what this means`

> The last option is not a joke and we expect it to be common. If most
> families pick it, self-hosting is a technical fact about the product
> and not something to sell on.

**22. Do you belong to a co-op, or know one that might want this?**
`Yes` · `No` — plus **Which one?** *(free text, optional)*

> The bridge to instrument B. Warm introductions from a member family
> are the only realistic way into a co-op.

### A4. Contact

**23. Your name** *(optional)* · **24. Email for a reply** *(optional)* ·
**25. Would you talk to us for twenty minutes?** `Yes` · `No`

---

## Instrument B: co-op educators

Roughly six minutes. Written for someone who may never have opened
Bede, so it explains as it asks. Ordered so the co-op describes itself
before we ask anything of it.

### B1. Your co-op

**1. Your role.**
`Director or board` · `Teaching parent` · `Hired tutor or teacher` · `Curriculum lead` · `Member parent`

> The most important question on the form, because it determines whether
> anything else this person says can become a decision.

**2. How many families are in your co-op?** `Under 10` · `10-25` · `25-50` · `50-100` · `More than 100`

**3. Which grade bands do you serve?** `K-2` · `3-5` · `6-8` · `9-12` *(multi)*

**4. How often do you meet, and what happens on the other days?** *(free text)*

> The single most useful free-text box on the form. Most co-ops meet
> once or twice a week, and the other three or four days are the parent
> alone at the kitchen table. That gap is the whole opportunity, and we
> should hear it described in their words rather than assume it.

**5. Does the co-op set curriculum, or does each family choose?**
`Co-op sets it` · `Co-op recommends, families choose` · `Entirely up to each family`

> Determines the relationship. Bede's constitution puts the parent
> first in its authority order, so a co-op that sets curriculum for its
> members is a case the product has never been designed against.

**6. Does your co-op hold a statement of faith or a required tradition?**
`Yes, and it is specific` · `Yes, broadly Christian` · `No` — plus **Which?** *(optional free text)*

> Bede ships a Catholic-scoped Saints & Catechism module and a
> deliberately denomination-neutral Scripture module beside it. Whether
> that split works for a co-op with a written statement of faith is
> something only they can tell us.

### B2. Would this get in front of your families

**7. What would you need to see before putting an AI tutor in front of
your member families?** *(free text)*

> The real gate, asked openly rather than guessed at with checkboxes.

**8. What is your co-op's position on an AI talking to a child without
an adult in the room?** *(free text)*

> Expected to be the hardest objection, and one Bede has real answers
> to: a written constitution, per-turn moderation, an encrypted audit
> log, and no child-facing surface that ranks children against each
> other. We ask before we answer, because the objection as they phrase
> it is worth more than our anticipation of it.

**9. If your co-op used Bede, what role would it play?**
`We would require it` · `We would recommend it` · `We would tell families it exists` · `We would let families find it themselves` · `We would not`

**10. Who decides something like this?**
`Director alone` · `Board vote` · `Member vote` · `Each family independently` · `Not sure`

**11. Who would run the software?**
`A computer the co-op owns` · `Each family's own computer` · `We would want it hosted for us` · `No idea, and that matters`

> Bede is self-hosted by design. A co-op-owned server is a deployment
> shape that exists in `docs/DEPLOYMENT_TOPOLOGY.md` as a stated future
> case and has never been built. If co-ops want it, that changes a
> roadmap.

**12. Would you host an onboarding session for member families?**
`Yes` · `Maybe` · `No`

### B3. Does the method fit how you teach

**13. Bede asks rather than tells, and runs on narration. Does that fit
how your co-op teaches?**
`Fits well` · `Partly` · `Conflicts with how we teach` · `Not sure yet`

**14. Which subjects should Bede stay out of for you?** *(multi-select,
plus "none")*

> A co-op that teaches Latin in person every week does not want Bede
> teaching Latin. Knowing which subjects are already covered in the room
> tells us what Bede is for in a co-op, which is probably not the same
> thing it is for at a kitchen table.

**15. What do your families struggle with most between meetings?** *(free text)*

### B4. Money

**16. Does your co-op collect fees or hold a budget?**
`Yes, and we buy curriculum with it` · `Yes, but only for space and events` · `No, families pay their own way`

**17. If your co-op paid, what would work?**
`One site license for the whole co-op` · `Per family, billed to the co-op` · `Per family, billed to each family` · `We would not pay, families would`

**18. Per family per month, what would your families accept?**
`Under $10` · `$10-20` · `$20-40` · `$40-75` · `More than $75`

> A single band rather than the four-question block used with parents.
> An educator is estimating on someone else's behalf, so the extra
> precision would be false.

### B5. Contact

**19. Your name** · **20. Co-op name** · **21. Email** · **22. Would you
take a call?** `Yes` · `No`

> Contact fields are optional here too, but an educator survey with no
> way to follow up has wasted the harder half of the work. The form says
> so plainly rather than pretending otherwise.

---

## The in-app short set

The in-app prompt (`BetaSurveyModal.tsx`) is **not** instrument A. It
interrupts a parent who opened the Progress page to look at their
children, so it carries five questions and links out to the full form for
anyone willing to keep going.

The five, taken verbatim from instrument A so their answers pool with the
hosted form's rather than forming a second dataset:

| # | Question | From |
| --- | --- | --- |
| 1 | How many school days has your child actually used Bede? | A1 |
| 2 | What happened to your own teaching time? | A5 |
| 3 | When your child narrates to Bede, what Bede does with it is: | A6 |
| 4 | Has Bede ever said something you had to correct? (+ what was it) | A7 |
| 5 | What one thing would make Bede genuinely useful to your family? | new |

Chosen because each needs someone who has actually used the product, and
because a family that answers nothing else still leaves the four facts
the beta most needs. Pricing is deliberately absent: it is the section
most likely to make someone abandon a prompt, and asking for a number in
a modal produces a worse answer than asking for it on a page someone
chose to open.

**When it appears.** Only for a parent, only on the Progress page, only
once that student has at least `MIN_ASSESSMENTS_BEFORE_SURVEY` (3)
recorded narration assessments, and only if the deployment has
`FEEDBACK_EMAIL` configured. The evidence gate matters: the first
question asks how many days Bede was used, and a family who tried it once
would file a first impression alongside a month's experience.

**How dismissing it works.** "Not now" and the corner X defer for
`DEFER_DAYS` (14). "Don't ask me again", and submitting, close it
permanently on that device. A parent who dismisses a prompt mid-task has
not declined the survey, and treating that as a permanent no would
silently lose the response. Stored per device, not per student, since the
questions are about the family.

**Locale.** The prompt is translated, but the question labels and answer
values it *submits* are always English. A Spanish-reading parent answers
the same question as everyone else, and a translated wire value would
split that question into one bucket per locale.

---

## Running it

**Recruiting beta parents.** The in-app prompt reaches families already
using Bede and needs no recruiting at all. For the rest, the hosted form
link goes out with the beta welcome email and in the end-of-session
summary email. Families who stopped using Bede are the ones worth
chasing individually, and are the least likely to answer an in-app
prompt, since they are not in the app.

**Recruiting co-op educators.** No list exists. In order of expected
yield: warm introductions from beta families (question A22 exists for
this), state and regional homeschool association directories, co-op
Facebook groups and email lists (post the link, do not spam members
individually), and homeschool conventions. A director who agrees to a
twenty-minute call is worth more than fifty form responses, and the form
should be treated partly as a way to find those people.

**Sample size, honestly.** We will not get a statistically meaningful
sample in a first beta and should not present results as though we did.
Thirty parent responses and ten co-op conversations would be a good
outcome, and would be enough to kill or confirm a pricing shape, not
enough to claim anything about learning outcomes. Say so in any summary
that leaves this repository.

**Reading the results.** Sort by question A1 before reading anything
else. Weight a six-week family over a three-session one, and read every
"we stopped using it" response in full before reading any of the
positive ones. On price, use the four-question block to find the range
where "bargain" and "expensive but worth it" cross, and check it against
question A14. If the range sits below what the anchor suggests families
already spend, the problem is positioning, not price.

**What happens to the answers.** They arrive as email in the operator
inbox and are not stored in any database. There is no analytics tool, no
form service, and no third party in the path. If a summary is ever
published, it carries no names and no co-op names without asking first.

---

## Keeping the three channels honest

The three delivery channels drift apart the moment one is edited alone.
The rule is the one this repository already applies to duplicated facts:
where the same question lives twice, add a check that they agree.

- `homeschool-tutor/src/components/BetaSurveyModal.test.tsx` asserts the
  in-app prompt's questions against the short set named here.
- The hosted pages share `site/assets/feedback-form.js`, which derives
  its labels from each page's own markup rather than a separate map, so
  a question renamed on the page cannot arrive in the inbox under its
  old name.
- Both hosted pages and the in-app prompt post to the same endpoint with
  the same `beta_survey` category, so everything sorts into one place in
  the inbox regardless of where it was answered.

See CLAUDE.md's "Carry Out the Decision, Don't Just Record It".
