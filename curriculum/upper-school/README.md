# Prioritized upper-school content intake

The owner authorized substantive Grades 9–12 content development ahead of
unfinished Grade 8 and requested rapid reuse of the already identified open
repositories. Preserve Grade 8 and its three accepted lesson packages.

This directory acquires exact, attributed **local review copies** of existing
resource selections. It is not another lesson factory, a live tutor corpus, or
a declaration of complete courses. Continue using the existing production
specification and development-only factory for authored lesson packages.

## Intake

`open-resources.json` identifies the existing selections and distinguishes
downloadable review copies from references that cannot be indiscriminately
copied. No new textbook or modern translation is silently substituted.

Run `python3 curriculum/upper-school/intake.py` to acquire the enabled review
copies into ignored `generated-artifacts/upper-school-sources/`. Each run writes
an acquisition report containing original URLs, resolved URLs, exact byte
counts, SHA-256 hashes, attribution, restrictions and failures. An unchanged
valid copy is reused. Failed or invalid downloads are not promoted to source
files. The process returns failure if any requested acquisition fails.

Wallace's expected hash is bound to the edition already inspected in the
replacement register; a changed copy is rejected, not silently substituted.
Requests to a given host are serialized and queued requests stop after a
`Retry-After` response. Recorded host cooldowns persist into subsequent runs.
Do not bypass server delays by changing download paths or using an unverified
mirror.

Gutenberg review copies retain their full notices. They are not cleared for
paid redistribution with Gutenberg marks, nor asserted public domain worldwide.
Do not feed them to the live tutor or enable training. The Wallace book retains
its CC BY 3.0 license; Bede cannot claim proprietary ownership of its text.
Selected Python 3.14 tutorial chapters and their complete license page are
also acquired as unchanged archival HTML in `.txt` files. Scripts are never
executed, and images and linked assets are not downloaded. Keep the license
snapshot and copyright notices with the documentation. These are references
for educator-led computing instruction, not beginner-ready lessons by
themselves; the tutorial itself assumes prior programming experience.

The University of North Georgia history source remains a bounded prose-only
link selection, not a downloaded whole book containing excluded media.

The source report is technical acquisition evidence only. It is not an
authenticated rights approval, academic review, accessibility certification or
completion certificate. No code changes the runtime source gate or bypasses
institutional promotion.

## Course use

- Grade 9: retain the existing nine teaching weeks and exact H/M/B crosswalk.
  Use the locally pinned resources to develop the remaining instruction.
- Grades 10–12: reuse these resources only where their level and topic fit.
  A Latin grammar or Algebra I/II reference does not supply four distinct years
  of language, Geometry, advanced mathematics, science or humanities courses.
- Both audiences: shared nondevotional academics, adult-controlled teaching
  and assessment; optional faith formation remains separate.

The owner now requires ordered PR delivery followed by verified publication
in demo and enrolled Bede. This increment publishes source work for review,
not a completed curriculum or runtime activation. Source rights, separate
adult keys, safe release checks and learner privacy remain required.
No real learner data or paid services are introduced.

See [actual intake, checks and remaining work](INTAKE-STATUS.md) for the
distinction between downloaded sources, authored teaching and ready curricula.

## First authored extension

- [Week 10 mathematics: student lessons](grade-9-week-10-math-student.md)
- [Week 10 mathematics: adult teaching and checked keys](grade-9-week-10-math-teacher.md)
- [Attributed Wallace §4.1 reference adaptation](wallace-4-1-review-extract.md)
- [Week 10 computing: five sessions and separate adult key section](grade-9-week-10-computing.md)
- [Week 10 biology: meiosis instruction and paper investigation](grade-9-week-10-biology.md)
- [Week 10 literature, history and Latin: learner instruction](grade-9-week-10-humanities.md)
- [Week 10 humanities: separate adult keys and review criteria](grade-9-week-10-humanities-teacher.md)
- [Confirmed beta target and readiness criteria](BETA-TARGET.md)

All six Week 10 academic subjects now have authored local review drafts.
This does not complete the additional weekly strands, the remaining Grade 9
year, Grades 10–12, independent academic review or factory promotion.
The factory's existing licensed-content authentication requirement remains
unchanged: these files are local content-review material, not an exception
that makes licensed material eligible for automatic runtime ingestion.
