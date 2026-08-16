# Pricing research: bundling evidence

> **What this is.** The evidence base behind the commercial entries in
> [docs/DECISIONS.md](DECISIONS.md) — specifically entry 13, whether the Family
> Membership should be broken into à la carte components. Every claim here
> names the study it rests on, states what class of evidence that study is, and
> states where it stops.
>
> **What this is not.** Not the decision. The register carries state; this
> document carries the argument, per the register's own "where a design
> document and this register would say the same thing twice" rule. If the two
> disagree, the register is authoritative about *what was decided* and this
> document is authoritative about *why anyone thought so*.

---

## 1. The honest framing, before any finding

**Most of the bundling literature is not statistical.** Of the eleven papers
retrieved for this question, nine are analytical or computational —
game-theoretic models, closed-form optima, mixed-integer programs — whose
conclusions hold *conditional on their assumptions about the distribution of
consumer reservation prices*, not because anyone observed a market. Two carry
statistical evidence, and they are the two that constrain how much weight the
other nine can bear.

That distinction is the single most important thing in this document, because
the assumption every model turns on — **the distribution of household
reservation prices across Bede's five components, and how those valuations
correlate** — has never been measured for Bede. Change that assumption and
several of the papers below reverse.

So the literature is being used here for the shape of the answer, not the
number. It narrows the option space from "anything" to a small set, rules one
option out fairly firmly, and names which component is the one to unbundle if
any is. It cannot tell us the price.

**The measurement that would settle it is already commissioned.**
[docs/BETA_SURVEY.md](BETA_SURVEY.md)'s price-and-unit questions are the
instrument. Entry 13 is `open` against that, deliberately, rather than closed
on theory.

### Evidence classes used in this document

| Class | Meaning | What it can support |
| --- | --- | --- |
| Analytical | Closed-form model, assumptions stated | "Under these conditions, X dominates Y" |
| Computational | Numerical solution of a model | Same, plus behaviour where no closed form exists |
| Empirical | Observed market data, estimated | "In this market, X was worth Y" |
| Meta-analytic | Pooled effect across studies | "This effect is/is not robust" |

---

## 2. The corpus

Retrieved through Scite. **Editorial notices were checked on every paper; none
carries a retraction, correction, or expression of concern.** Smart Citation
tallies are reported because they are a weight signal, not a truth signal — a
contrasting citation means someone disputed the finding in print.

| Study | Class | Citing pubs | Smart Citations (sup/con) | Used for |
| --- | --- | --- | --- | --- |
| Wu et al. (2008) | Computational | 127 | 0 / 1 | The central finding (§3.2) |
| Prasad et al. (2010) | Analytical | 141 | 1 / 0 | Which component to unbundle (§3.3) |
| Honhon & Pan (2017) | Analytical | 52 | 0 / 2 | Nesting, discount structure (§3.4) |
| Xu et al. (2018) | Analytical | 12 | 0 / 0 | Ruling out full à la carte (§3.1) |
| Rabbani et al. (2017) | Computational | 7 | 0 / 0 | Cross-selling loss (§3.1) |
| Bakos et al. (1999) | Analytical | 217 | 1 / 0 | Per-family pricing (§3.5) |
| Thanassoulis (2007) | Analytical | 57 | 3 / 1 | Competitive caution (§4.1) |
| Liu & Yu (2017) | Analytical | 1 | 0 / 0 | Discount bound — weak (§3.6) |
| Koschat & Putsis (2002) | **Empirical** | 44 | 3 / 0 | Unbundling premiums (§4.2) |
| Scheibehenne et al. (2010) | **Meta-analytic** | 1,049 | 29 / 4 | Killing a bad argument (§3.7) |
| Yan & Bandyopadhyay (2011) | Analytical | 69 | 1 / 0 | Retrieved, not relied on¹ |

¹ No abstract was available through the retrieval, so its finding cannot be
characterised precisely enough to cite. Listed for completeness rather than
quietly dropped — a corpus that only lists the papers that agreed with the
conclusion is not a corpus.

**One paper is referenced but not in the corpus, on purpose.** Bakos and
Brynjolfsson's 1999 *Management Science* result — that under zero marginal cost
and i.i.d. valuations, pure bundling is optimal for a multiproduct monopolist —
is foundational here and was **not retrieved directly**. It reaches this
document only as reported and quoted by Wu et al. (2008), who cite it as their
own point of departure. It is therefore attributed to Wu et al. throughout, and
does not appear in the reference list. Citing a paper nobody read, because
another paper described it, is how a literature review becomes folklore.

---

## 3. What the evidence establishes

### 3.1 A flat à la carte grid is the option ruled out

For complementary products, adopting a pure or mixed bundling strategy is more
profitable than selling each product separately **regardless of the degree of
complementarity**, and once complementarity is large enough, pure bundling is
the most profitable of the three (Xu et al., 2018). Separately, optimising
assortment and price while *ignoring* cross-selling between complementary
categories, or forbidding bundling, produces significant profit loss (Rabbani
et al., 2017).

Bundling's value here is not primarily price discrimination. It comes from
**increased sales**: a firm that understands its customers may buy multiple
component types offers bundles, which incentivises customers to buy more
(Honhon & Pan, 2017).

**Limit.** Both are analytical/computational under stated demand structures.
Neither observed a market. What they establish is that "sell all five
separately at component prices" is not a candidate worth modelling further,
not that any particular bundle price is right.

### 3.2 The central finding: neither pole, a middle path

Wu et al. (2008) solve customised bundle pricing — the customer chooses up to
*N* goods from a pool of *J* — as a nonlinear mixed-integer program, and
compare it against both pure bundling and individual sale.

Their finding, in their own terms: customised bundling enhances profits **when
consumers do not place positive values on all goods**, and *this consumer
characteristic is much more important than the shape of the valuation
distribution* in determining the optimal pricing scheme. It also outperforms
both simpler schemes **under incomplete information about consumer reservation
values**.

Two things make this the load-bearing paper for Bede.

First, the condition it turns on is almost certainly met. A household with one
six-year-old has little use for messaging; a single-child household has little
use for a Family Portal roster. These are not marginal consumers — they are
ordinary ones.

Second, the robustness clause matters more than the headline. *Incomplete
information about reservation values* is precisely Bede's state: nobody has
measured them (§1). A result that survives not knowing the distribution is
worth more here than one that requires knowing it.

**Limit.** Numerical, not empirical. The paper also notes a real cost this
document takes seriously in §3.7: menu overhead and the cognitive cost
consumers face evaluating large offer sets bound how many bundles are worth
offering.

### 3.3 Which component to unbundle has a named answer

Locuto messaging has direct network externality — its value to a household
rises with the size of the user base. Bede Tutor has none; it is worth the same
to the first family as to the thousandth.

Prasad et al. (2010) model exactly this asymmetry: a monopolist with one
product in each of two categories, facing heterogeneous consumers, where the
products may be **asymmetric in degree of network externality or marginal
cost**. Their result:

- **Pure bundling** is more profitable when *both* products have low marginal
  cost **or** high network externality.
- **Pure components or "mixed bundling-1"** — the bundle plus *one* product
  standalone, the other purchasable only inside the bundle — is more profitable
  when the products **diverge** in cost and externality (e.g. only one product
  has network externality).
- Traditional mixed bundling (everything available both ways) is optimal only
  in the remaining cases.

Bede is in the divergent case, not the symmetric one. So the structure the
literature points at is not "unbundle" or "don't" — it is *mixed bundling-1*,
which fixes both the count (one standalone) and the identity (the component
**without** network externality, i.e. the tutor).

The corollary is the part worth stating explicitly: **Locuto must stay
bundle-only.** Selling it standalone and cheaper cannibalises the bundle
without growing the installed base faster than the bundle does, which is the
one thing its value actually depends on.

**Limit.** Analytical, two-product, monopolist. Bede has five components, not
two, and the co-op tier is not a monopolist setting. The result transfers as a
structural principle, not as a solved optimum.

### 3.4 Tiers should nest, not fan out

Honhon & Pan (2017) show that **each** bundling strategy can be optimal, and
characterise the structure of the optimal assortment: when consumers benefit
from consuming the components jointly, the products in the optimal assortment
**form nested sets**. When they do not benefit from joint consumption, the
bundles should be offered at a **positive discount**.

Applied: Tutor ⊂ Family ⊂ Co-op ⊂ Network, each containing the one before it.
Never a feature grid where a family assembles a combination nobody designed.
Entry 10 already refused a feature ladder for a different reason (no gating to
build); this is an independent argument arriving at a compatible shape.

The joint-consumption clause also tells us something about discount depth: to
the extent Bede's components genuinely reinforce each other in use — the tutor
producing what the Family Portal reports, oversight governing both — the
nesting substitutes for discount rather than adding to it.

### 3.5 Per-family pricing survives the analysis

Entry 10's load-bearing choice is a per-family price with no per-child
multiplier. Bakos et al. (1999) address the closest available question: whether
sharing an information good within small social communities undermines seller
profit. Their result is that **so long as consumers share within teams of
constant size, sharing always increases profit** under a general set of
conditions — and can do so even when sharing is inefficient in the narrow
sense that consumer-side redistribution costs more than producing another unit.

A household is a sharing team of roughly constant size. The finding does not
prove $199 is right; it removes the objection that per-family pricing leaks
value that per-seat pricing would capture.

**Consequence for the page.** Entry 10's per-child table stays what it is —
arithmetic shown to make the inversion visible — and does not become a set of
SKUs. Turning those rows into purchasable units would be a per-seat model
wearing a per-family label.

### 3.6 Keep the bundle discount modest — weak evidence, real mechanism

Liu & Yu (2017) object to a standing assumption in this literature: that a
consumer's willingness to pay for a bundle equals the sum of their separate
reservation prices for the components. Since full mixed bundling is a discount
conduct — the bundle price must be below the sum of the standalone prices —
they argue that discount belongs inside the WTP calculation. With heterogeneous
reservation prices under a uniform distribution and Stackelberg pricing, they
reach the opposite conclusion to the mainstream: **profit under full mixed
bundling is less than under pure components**.

**This is the weakest paper in the corpus and is treated as such.** One citing
publication, no Smart Citations either way, a specific pricing game. It is
recorded because the *mechanism* is real and cheap to respect: it bounds how
deep the bundle discount should go, not whether to bundle. A modest discount
sits outside the regime where their reversal bites.

### 3.7 "A menu would confuse parents" is not supported

This is the argument most likely to be made against any à la carte option, and
the evidence does not support it. Scheibehenne et al. (2010) meta-analysed 63
conditions from 50 published and unpublished experiments (**N = 5,036**) and
found a **mean effect size of virtually zero**, with considerable variance
between studies. They identify several potentially important *preconditions*
for choice overload but **no sufficient conditions**.

This is the highest-quality evidence in the corpus — the only pooled,
statistical result — and what it establishes is a negative: the folk claim is
not a sound basis for a design decision either way.

**The real reason to cap the menu is different and better founded.** Wu et al.
(2008) note that overhead grows with the number of bundles offered and that
consumers' cognitive cost in evaluating large offer sets is itself a motivation
for menu costs, so the number of bundles for sale should be limited. Four
visible offers, on that basis. Same cap, honest reason.

---

## 4. Two findings that cut against the recommendation

A corpus assembled to support a conclusion is not evidence. These are the
results that push the other way.

### 4.1 Competitive mixed bundling extracts consumer surplus via switching costs

Thanassoulis (2007) finds that in imperfectly competitive industries,
competitive mixed bundling **lowers consumer surplus overall and raises
profits** — specifically when buyers incur *firm-specific costs* or have
shop-specific tastes. The result **reverses** when differentiation between
components, rather than between firms, is what matters.

Bede accumulates firm-specific costs by design: mastery history, the work
ledger, lesson bookmarks, a learner profile. A family that leaves loses those.
That is the exact condition under which the paper says mixed bundling transfers
surplus from buyer to seller.

This is not a reason to avoid mixed bundling. It is a reason to know which
mechanism is producing the profit, and to state that leaning on accumulated
lock-in is a positioning choice with a cost, not a free lunch — particularly
for a product whose constitution puts the family's authority first.

### 4.2 Unbundling premiums can be substantial, empirically

Koschat & Putsis (2002) is the corpus's only market-data study: a hedonic
analysis of magazine advertising rates and reader demographics, estimating
implicit prices of reader characteristics where publishers can sell all readers
(pure bundling), specific segments (pure components), or both. Their finding is
that **the price and revenue premiums earned by unbundling can be substantial**.

That is a real empirical counterweight to §3.1. Where segments are identifiable
and their valuations genuinely differ, selling to them separately pays. The
reconciliation is that Bede *already does this* — the Co-op and Network tiers
are segment-priced offers, not component-priced ones. The premium is captured
by segmenting the buyer, not by shredding the product.

---

## 5. What is outside the economics entirely

Two of the five components cannot be priced off, and no finding above bears on
it.

**Parent tools and oversight**, and **verified access**, are not features. A
membership sold with the guardrails removed would make the safety posture a
paid upgrade — a cheaper Bede that watches a child less. `docs/CONSTITUTION.md`'s
non-negotiable rule to protect the full dignity, privacy, safety and
developmental needs of every child does not leave that open as a commercial
option, whatever a model says about profit.

They stay in every membership at every tier, whatever entry 13 resolves to.
This constraint is stated here so that a future pricing exercise inherits it
rather than rediscovering it.

---

## 6. The recommendation this evidence supports

Stated as a recommendation, not a decision — entry 13 is `open` and awaits a
founder ruling informed by beta pricing responses.

1. Keep the Family Membership as the headline bundle. Do not build an à la
   carte grid (§3.1).
2. Add **exactly one** standalone: Bede Tutor (§3.3).
3. Keep Locuto messaging, the Family Portal, oversight and verified access
   bundle-only (§3.3, §5).
4. Keep the tiers nested: Tutor ⊂ Family ⊂ Co-op ⊂ Network (§3.4).
5. Keep the bundle discount modest rather than steep (§3.6).
6. Cap the visible menu at four offers, on menu-cost grounds (§3.7).
7. Keep per-family pricing; the per-child table stays arithmetic, not SKUs
   (§3.5).

**What would change this.** If beta responses show households value all five
components positively and roughly uniformly, §3.2's condition fails and pure
bundling — no standalone at all — becomes the stronger answer. If they show
wide dispersion with weak correlation across components, the case for a
customised "pick N" offer strengthens beyond the single standalone recommended
here. Both are answerable from the survey; neither is answerable from the
literature.

---

## 7. Standard of evidence for this document

Recorded so the next research pass is held to the same bar rather than a
remembered one.

1. **Every claim names its study.** No sentence of the form "research shows"
   without a citation attached to it.
2. **Every study's evidence class is stated** (§2's table). An analytical
   result and a meta-analysis do not carry the same weight and must not read
   as though they do.
3. **Editorial notices are checked before citing**, and the check is reported
   whether or not it found anything.
4. **Nothing is cited that was not retrieved.** A result known only through
   another paper's description is attributed to the paper that described it
   (see §2's note on Bakos & Brynjolfsson, 1999).
5. **Contrary findings get their own section** (§4), not a subordinate clause.
6. **Weak evidence is labelled weak in the sentence that uses it** (§3.6), not
   only in a table someone may not reach.
7. **The limits of each finding are stated with the finding**, not collected in
   a disclaimer at the end.

---

## References

Bakos, Y., Brynjolfsson, E., & Lichtman, D. (1999). Shared information goods.
*The Journal of Law and Economics, 42*(1), 117–156.
https://doi.org/10.1086/467420

Honhon, D., & Pan, X. A. (2017). Improving profits by bundling vertically
differentiated products. *Production and Operations Management, 26*(8),
1481–1497. https://doi.org/10.1111/poms.12686

Koschat, M. A., & Putsis, W. P. (2002). Audience characteristics and bundling:
A hedonic analysis of magazine advertising rates. *Journal of Marketing
Research, 39*(2), 262–273. https://doi.org/10.1509/jmkr.39.2.262.19083

Liu, W., & Yu, H. (2017). Pure components vs full mixed bundling when
Stackelberg pricing. *Journal of Systems Science and Information, 5*(5),
435–445. https://doi.org/10.21078/jssi-2017-435-11

Prasad, A., Venkatesh, R., & Mahajan, V. (2010). Optimal bundling of
technological products with network externality. *Management Science, 56*(12),
2224–2236. https://doi.org/10.1287/mnsc.1100.1259

Rabbani, M., Salehi, R., & Farshbaf-Geranmayeh, A. (2017). Integrating
assortment selection, pricing and mixed-bundling problems for multiple retail
categories under cross-selling. *Uncertain Supply Chain Management*, 315–326.
https://doi.org/10.5267/j.uscm.2017.5.001

Scheibehenne, B., Greifeneder, R., & Todd, P. M. (2010). Can there ever be too
many options? A meta-analytic review of choice overload. *Journal of Consumer
Research, 37*(3), 409–425. https://doi.org/10.1086/651235

Thanassoulis, J. (2007). Competitive mixed bundling and consumer surplus.
*Journal of Economics & Management Strategy, 16*(2), 437–467.
https://doi.org/10.1111/j.1530-9134.2007.00145.x

Wu, S., Hitt, L. M., & Chen, P. (2008). Customized bundle pricing for
information goods: A nonlinear mixed-integer programming approach. *Management
Science, 54*(3), 608–622. https://doi.org/10.1287/mnsc.1070.0812

Xu, Q., Xu, B., & Wang, P. (2018). Bundling strategies for complementary
products in a horizontal supply chain. *Kybernetes, 47*(6), 1158–1177.
https://doi.org/10.1108/k-02-2017-0082

Yan, R., & Bandyopadhyay, S. (2011). The profit benefits of bundle pricing of
complementary products. *Journal of Retailing and Consumer Services, 18*(4),
355–361. https://doi.org/10.1016/j.jretconser.2011.04.001
