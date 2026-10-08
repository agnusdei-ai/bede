# Intellectual Property

**What this is.** The IP position in one place: what Bede's intellectual
property consists of, who owns each part, which claims are already enforced by
tests, and the two acts that have to happen before the ownership this
repository asserts is true in fact.

**What this is not.** This is not legal advice. The reasoning here is a founder's and an
agent's, grounded in this repository's own facts; every filing decision needs a
registered attorney, and the places where one is required are named as such.

Before this document the IP work was real but scattered across five files and
one register entry, with no single place that said what the position was. This
gathers it. Where a fact belongs to the decision register, this points at the
entry rather than restating it — `docs/DECISIONS.md` is the state, this is the
argument and the runbook.

---

## 1. What the property is, and who owns it

| Asset | Status |
| --- | --- |
| The Bede codebase (all directories except `agent-governance/`) | Proprietary. Root `LICENSE`, all rights reserved. |
| `agent-governance/` | Apache-2.0 to everyone. Register entry 18. |
| The **BEDE** mark, the Agnus Dei name and emblem | Reserved. Root `LICENSE` §5; unregistered, used with ™. |
| `agnusdei.ai` and the brand assets | Held with the rest. |
| Curriculum content under `data/` | Authored for this project; sourcing rules in `docs/CONTENT_CONTRIBUTING.md`. |

**The named owner is Agnus Dei Technologies, LLC**, stated on the root
`LICENSE`'s first line and derived from there by test rather than restated
anywhere (§3 below).

**Founder-authored work reaches the company by assignment, not by default.**
Copyright in software vests initially in its author, so a company formed around
existing work takes title through a written instrument rather than
automatically — which is why §4's runbook ends in §5's assignment, and why that
step is the one diligence looks for.

## 2. The Apache-2.0 carve-out

`agent-governance/` is licensed to everyone under Apache-2.0, including for
commercial use and redistribution. The reasoning, and why Apache over MIT or
CC BY, is **register entry 18** — including its 2026-10-08 amendment correcting
the licensor's name.

Two consequences matter outside that entry:

- **The grant includes an express patent licence** (Apache-2.0 §3), published
  and not withdrawable. Anyone assessing what that covers should read §3 of
  that licence directly rather than a paraphrase here.
- **It is an encumbrance on the copyright**, so an assignment of this codebase
  has to acknowledge it rather than warrant the work unencumbered. §5's
  template does.

## 3. What is already enforced rather than promised

Three guards, each verified by breaking it:

- **One licensor, derived.** `homeschool-api/tests/test_license_carveout.py`
  reads the holder out of the root `LICENSE`'s own copyright line and asserts
  the `NOTICE`, all seven shipped source headers, and the §6 carve-out name
  that same entity. A rename that reaches some files and not others fails.
- **No second licensor.** The same file fails if *any* copyright line anywhere
  in `agent-governance/` names a different entity. The first guard catches a
  half-finished rename; this catches a new wrong entity appearing beside the
  right one, which is how the original defect got in.
- **One trademark attribution.** `tests/test_trademark_attribution.py` asserts
  the sentence a family actually reads — rendered by `BedeMark.tsx`, which
  exists twice — is identical in both apps and names the owner on the root
  `LICENSE`. Before it, nothing checked either.

These make the *claims* consistent. They cannot make them true; §4 does that.

## 4. Formation and assignment — the two acts outstanding

Nothing in this section is blocked on software. Steps 1-3 are days and a few
hundred dollars.

1. **Confirm the entity name.** The Texas Secretary of State confirms
   availability by phone at no charge; a comptroller search is also free. As of
   2026-10-08 no entity named "Agnus Dei Technologies" appeared in any index
   searched — but indexes are not the registry, and the phone confirmation is
   the answer that counts.
2. **File the Certificate of Formation** (Texas Form 205, via SOSDirect).
   Verify the current fee and turnaround at filing time.
3. **Get the EIN.** Free and immediate from the IRS. Never pay a service for
   this.
4. **Adopt an operating agreement.** Not filed anywhere; part of what makes
   the liability shield hold for a single-member LLC.
5. **Execute the IP assignment** in §5 — the step most often skipped and the
   one diligence always looks for. Do it as part of formation rather than
   later: it is a signature on a document already drafted, and it is what
   carries title from the author to the company.
6. **Open a business account** and route license revenue through it rather
   than a personal account. Commingling is the other thing that pierces the
   shield, and `docs/SELLING_BEDE.md`'s deposit terms assume one.

Only then the trademark application (§6), in the LLC's name.

**This document is the method, never the state.** Where each step has got to
is not tracked here, and deliberately not in the public decision register
either: how far along a private company is in perfecting its own title is not
a fact this repository needs, and it is readable by anyone. Keep that with the
company's records.

## 5. The IP assignment

A working template, written to be signed by one person on both sides — the
founder individually, and the LLC they wholly own. That symmetry is what makes
a self-prepared version reasonable here: there is no counterparty whose
interests diverge, and a cleaner version can be re-executed later by the same
two parties under §5 of the agreement itself. Have a Texas business attorney
review or replace it when budget or a diligence event arrives.

**Do not sign it before the LLC exists.** The effective date must fall on or
after formation.

**Fill the brackets in your own copy, never in this one.** The formation date,
the file number, the addresses and the signatures belong to the signed
instrument and the company's records. Nothing in this repository reads them,
and a committed copy carrying them would publish a private company's filing
particulars for no benefit.

Three clauses carry the weight, and are the ones to check survive any edit:

- **§2(b) assigns the mark *together with its goodwill*.** A trademark
  assignment that omits goodwill is void. This is the single most consequential
  sentence in the document.
- **§3 acknowledges the published Apache-2.0 grant** and makes the assignment
  subject to it, so §6(c)'s "free of liens and encumbrances" stays true.
- **§5 obliges further assurances**, which is what makes signing a rough
  version now safe: the upgrade path is written into the instrument rather than
  left to goodwill.

Replace everything in `[brackets]`.

### INTELLECTUAL PROPERTY ASSIGNMENT AGREEMENT

This Intellectual Property Assignment Agreement (this "Agreement") is made and
entered into as of **[DATE — on or after the LLC's formation date]** (the
"Effective Date"), by and between:

**Assignor:** [FULL LEGAL NAME], an individual residing at [ADDRESS]
("Assignor"); and

**Assignee:** **Agnus Dei Technologies, LLC**, a Texas limited liability
company formed on [FORMATION DATE], Texas SOS file number [FILE NUMBER], with
its principal place of business at [ADDRESS] ("Assignee").

**1. Background.** Prior to the formation of Assignee, Assignor individually
conceived, authored, and developed certain software, written materials, brand
assets, and related intellectual property comprising and supporting the product
and service known as **Bede** (collectively, the "Property"). Assignor is the
sole author and owner of the Property. Assignee was formed to own and
commercialize the Property.

**2. Assignment.** For the consideration described in Section 4, Assignor
hereby irrevocably sells, assigns, transfers, and conveys to Assignee, and
Assignee hereby accepts, all of Assignor's right, title, and interest,
worldwide, in and to the Property, including without limitation:

**(a) Copyright.** All copyrights and copyrightable works, whether registered
or unregistered, in and to the Bede software codebase, documentation,
curriculum content, prompts, written materials, and all source and object code
thereof, together with all registrations and applications therefor and all
rights to sue and recover for past, present, and future infringement.

**(b) Trademarks and goodwill.** The mark **BEDE**, the Agnus Dei name and
emblem, and all other trademarks, service marks, trade names, logos, and trade
dress used in connection with the Property, **together with all goodwill of
the business symbolized by and associated with such marks**, and all
registrations, applications, and common-law rights therein, and all rights to
sue and recover for past, present, and future infringement or dilution.

**(c) Domain names and online accounts.** The domain name `agnusdei.ai` and any
other domain names, social media handles, and hosting or repository accounts
used in connection with the Property.

**(d) Other intellectual property.** All trade secrets, know-how, designs,
inventions (whether or not patentable), and all patents and patent
applications claiming any such invention, and all other intellectual property
rights of any kind in or relating to the Property.

**3. Existing Licence — Acknowledged and Preserved.** Assignor and Assignee
acknowledge that prior to the Effective Date Assignor publicly released the
contents of the `agent-governance/` directory of the Bede codebase under the
Apache License, Version 2.0, which grants to all recipients a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright and
patent license as stated in that license. The assignment in Section 2 is made
**subject to** that existing license, which remains in full force and effect.
Assignee takes the assigned rights encumbered by it and shall honor it. Nothing
in this Agreement revokes, limits, or purports to revoke or limit any right
previously granted thereunder, and nothing herein grants any right in the BEDE
mark, which is expressly reserved.

**4. Consideration.** The assignment is made in consideration of Assignor's
membership interest in Assignee, the mutual covenants in this Agreement, and
other good and valuable consideration, the sufficiency of which is hereby
acknowledged.

**5. Further Assurances.** Assignor shall, at Assignee's reasonable request and
expense, execute and deliver such further documents and take such further
actions as may be reasonably necessary to perfect, record, or enforce
Assignee's rights in the Property, including executing any assignment in
recordable form required by the United States Patent and Trademark Office or
the United States Copyright Office.

**6. Representations.** Assignor represents and warrants that: (a) Assignor is
the sole owner of the Property; (b) Assignor has full right and authority to
make this assignment; (c) the Property is free of liens and encumbrances other
than the license described in Section 3; and (d) to Assignor's knowledge, the
Property does not infringe the intellectual property rights of any third party.

**7. Governing Law.** This Agreement is governed by the laws of the State of
Texas, without regard to its conflict-of-laws principles.

**8. Entire Agreement.** This Agreement constitutes the entire agreement
between the parties regarding its subject matter and supersedes all prior
understandings. It may be amended only in a writing signed by both parties. It
may be executed in counterparts, including by electronic signature.

**ASSIGNOR** — Signature: ________________  Date: __________
[FULL LEGAL NAME], individually

**ASSIGNEE — AGNUS DEI TECHNOLOGIES, LLC** — Signature: ________________  Date: __________
[FULL LEGAL NAME], Sole Member / Manager

### Before signing

- [ ] LLC formed; SOS file number and formation date in hand
- [ ] Effective Date on or after the formation date
- [ ] Both signature blocks completed — the founder signs twice, once in each
      capacity
- [ ] Signed original kept with the LLC's records
- [ ] Section 3 left in. Deleting it would make Section 6(c) inaccurate, since
      the Apache-2.0 grant is a real encumbrance that already exists
- [ ] **Nothing recorded with the USPTO for the BEDE mark yet** — there is no
      application to record against, and recording is what the §1060
      restriction in §6 attaches to. Assign now, file later, record after
      filing

## 6. Trademark — hold the filing until the first paid sale

Registration is worth doing properly rather than quickly.

**Common-law rights already exist** from use in commerce, and ™ requires no
registration — `BedeMark.tsx` uses it correctly today. What registration adds
is nationwide constructive notice, federal-court standing, and ®.

**Filing after the first paid sale is both cheaper and stronger:**

- A **use-based** (§1(a)) application avoids the intent-to-use route's separate
  statement-of-use fee.
- It avoids the assignment trap: under 15 U.S.C. §1060(a)(1) an intent-to-use
  application generally **cannot be assigned** before a verified statement of
  use, except to a successor to the applicant's whole ongoing business. Forming
  the LLC, assigning, and then filing in the LLC's name means that question
  never arises. Filing personally and assigning afterwards risks a void
  assignment.
- The goods-and-services description describes what is actually sold rather
  than what was planned.

**An application filed by the wrong applicant is void from the start and
cannot be cured by amendment** — the filing date and fee are lost. This is why
formation strictly precedes filing.

**Run a search before filing, and treat anything short of an attorney's as
preliminary.** A free knockout search over the relevant classes is worth doing
first because it is the cheapest moment to discover a conflict; it is **not
clearance**, and its results are working material for counsel rather than
anything this repository needs to carry.

## 7. Patent — no filing planned

**The decision: a patent gates nothing here, and no filing is planned.** A
patent publishes the method, costs tens of thousands and years to obtain,
issues against a version of a continuously-released product that has moved on,
and needs resources far beyond a beta to enforce. Commercial release does not
wait on one. Recorded here so the question reads as considered rather than
overlooked.

**The analysis is held with counsel, not here.** Which mechanisms might be
novel, what the disclosure timeline implies for which jurisdictions, and
whether anything clears prior art are questions for a patent attorney —
working material in which a partial, public, non-lawyer's answer helps nobody
who should have it and is freely readable by everyone who should not. If the
question is reopened, it is reopened with an attorney and the reasoning stays
in that channel.

## 8. Order of operations

1. Confirm the name (free)
2. Form the LLC, get the EIN (§4)
3. Execute the assignment (§5)
4. Operating agreement, business account
5. First paid sale
6. Trademark application, in the LLC's name (§6)
7. Patent only if an attorney's screen justifies it (§7)

**Related:** register entry 18 (the Apache-2.0 carve-out), root `LICENSE`
§§5-6, `docs/SELLING_BEDE.md` (producing a license key to sell), `README.md`'s
licence section.
