# Choosing an assessor

**Draft.** Use this to compare proposals. It is a list of questions, not a
judgment of any firm.

## Requirements

- A licensed CPA firm for SOC 2. Ask for the attesting partner's name and
  licence.
- An accredited AIUC-1 auditor, if AIUC-1 is in scope. Ask the AIUC-1
  program to confirm the firm's accreditation.
- One firm, or two firms that agree in writing to share evidence, so the same
  test results serve both engagements.
- No conflict of interest: the firm that writes or runs your controls cannot
  be the firm that examines them.

## Questions for every proposal

**Scope**
1. Will you confirm the system boundary in `README.md` §1 before the
   engagement starts, and in writing?
2. Which trust services categories do you recommend for this system, and why?
3. How do you treat self-hosted family installations and school-run machines?
4. How will you handle the AI and hosting providers: carve-out or inclusive?
   Which of their reports will you need?

**Type and timing**
5. Do you recommend a readiness assessment, then Type 1, then Type 2? What
   observation period do you recommend for a first Type 2, and what is the
   shortest you would accept?
6. Can the SOC 2 and AIUC-1 work run together, with one combined report or
   two coordinated reports?

**Testing**
7. Who does the penetration test and the AI red-team testing? Must it be your
   firm, or will you accept a named third party?
8. Will the AI testing adapt to what it finds, or use a fixed set of prompts?
9. What does recurring AIUC-1 testing involve after the first report, and how
   often?

**Evidence**
10. How do you sample changes for change management, and what do you need
    from GitHub to trace a change from request to deployment?
11. Which evidence can come from CI and repository history, and which needs a
    human record?
12. What would you treat as an exception, given a very small team with one
    person holding production access?

**Practical**
13. Fees, stated separately for readiness, Type 1, Type 2, AIUC-1 and any
    retesting.
14. The people who would work on the engagement, and their experience with
    education technology and with AI systems.
15. Two references from comparable small software companies.

## Comparing answers

Record each firm's answers side by side, with the date received. Choose on
scope clarity, independence and evidence approach first, and price second.
The owner makes the final choice.
