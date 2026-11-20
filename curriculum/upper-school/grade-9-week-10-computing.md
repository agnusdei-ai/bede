# Grade 9 Week 10: combining conditions

**Local review draft.** Five 30-minute sessions, 150 minutes total.
This original Bede instruction extends the existing Week 10 studio objective:
combine Boolean rules with `and`, `or`, and `not`, then test all logical cases.
The Python tutorial's selected control-flow and introduction chapters are
educator references, not compulsory unbounded learner reading.

## Objective and prerequisites

Given two explicitly Boolean inputs, build and explain a truth table, predict
a rule's result, and test its implementation on all four cases. Recognize
missing input as unknown rather than silently treating it as false.

Before beginning, ask the learner to explain `True` and `False` and trace one
simple `if` decision. If insecure, replace Day 1's extension with paper cards
labelled true/false and a single-condition rule. No cloud account or installation
is required: all tasks can be traced on paper. Python execution is optional in
an adult-approved local interpreter.

## Student teaching and tasks

### Day 1 — AND means both

**5m retrieve:** Is “not measured” the same as “measured and false”? Explain
your initial view; revisit it on Day 4.

**10m model:** A fictional equipment cabinet can be opened when an adult has
authorized access **and** a reservation is active. Let A mean authorization
and R mean active reservation. These are invented Boolean records, not an
access-control system to deploy.

With A=true and R=true, both conditions hold. With A=true and R=false, one
condition fails, so the rule is false.

**10m practice:** Complete a table for `(A,R)` equal to `(false,false)`,
`(false,true)`, `(true,false)`, `(true,true)`. Explain each row.

**5m exit:** Is checking only the two rows in the model enough to test the
rule on every possible pair? Explain what is missing.

### Day 2 — OR and NOT

**5m retrieve:** Describe AND without using its name.

**10m model:** In Boolean logic, `A or R` is true if at least one input is
true, including when both are true. It is not “one or the other but never
both.” `not A` reverses a Boolean input.

**10m practice:** Add columns for `A or R`, `not A`, and `not (A or R)` to
yesterday's four-row table.

**5m exit:** A learner says `not (A or R)` means “A is false or R is false.”
Find a row that tests that claim.

### Day 3 — read the grouping

**5m retrieve:** Give an OR row where both inputs are true.

**10m model:** Compare `(not A) and R` with `not (A and R)`. Parentheses
identify which whole condition is negated. For A=true, R=false, the first
expression is false and the second is true. Parentheses can change meaning.

**10m practice:** Evaluate both expressions on every row. Write a sentence
explaining each expression. Then translate “authorization is present and a
reservation is absent” into a parenthesized Boolean expression.

**5m exit:** Explain why testing just A=false, R=true would fail to reveal
that the two expressions differ.

### Day 4 — missing data is not false

**5m retrieve:** Revisit the opening question.

**10m model:** Use the supplied function below. `None` represents a missing
observation, not a false observation. This teaching function deliberately
returns `"unknown"` whenever either input is missing. It does not implement
the full set of possible three-valued logic simplifications.

```python
def cabinet_rule(authorized, reserved):
    if authorized is None or reserved is None:
        return "unknown"
    if type(authorized) is not bool or type(reserved) is not bool:
        raise ValueError("Use Boolean inputs or None")
    return authorized and reserved
```

**10m practice:** Predict the output for `(True, True)`, `(True, False)`,
`(None, True)`, `(False, None)`, and `("false", True)`. For the final example,
explain why a text label is not an accepted Boolean input. Trace on paper
before running it.

**5m exit:** Why would a function that silently converts the nonempty text
`"false"` to a Boolean be misleading here?

### Day 5 — independent application

**15m independent:** A fictional batch of book records should be flagged
when an identifier is missing **or** a duplicate has been detected. Inputs M
and D are Boolean, and all records are supplied examples, not learner data.

1. Write the rule and its complete four-row truth table.
2. Write the negation of the entire flagging rule. Explain it in words.
3. Give a case that distinguishes `not (M or D)` from `(not M) or (not D)`.
4. Decide what to report if the duplicate check was never performed. Explain
   why that does not establish that no duplicate exists.

**10m conference:** Explain your first answers before receiving feedback.
The adult records which answers were independent and which needed support.

**5m reflection:** Correct one error or invent a new rule and identify a
case that would expose an incorrect implementation.

## Delayed check

Seven days later, use 8 minutes within the following week's studio time:
let C mean “citation is present” and V mean “citation was verified.”
Write a rule for “citation is present but not verified,” test all four rows,
and explain why “not verified” does not necessarily mean “false.”

## Bede scaffolding and access

During supported practice, ask one question at a time:
“Which input is true in this row?”; “Which whole expression is negated?”;
“Have you tested all four pairs?”; “Is the value false, or do you lack evidence?”
Do not give the completed truth table during the independent check.

Allow exact read-aloud, enlarged print, dictated answers, physical Boolean
cards or a keyboard table. Those alternatives preserve logical reasoning;
paper-only work does not establish independent code execution skill.
No personal data, external service, physical cabinet or real security decision
is used. Stop for fatigue and split a session without increasing total time.

---

## Adult-only teaching key — separate before learner distribution

In row order FF, FT, TF, TT:

| Expression | FF | FT | TF | TT |
|---|---|---|---|---|
| A and R | F | F | F | T |
| A or R | F | T | T | T |
| not A | T | T | F | F |
| not (A or R) | T | F | F | F |
| (not A) and R | F | T | F | F |
| not (A and R) | T | T | T | F |

Day 1: the model omitted FF and FT. Day 2 counterexample: A=true, R=false
gives false for `not (A or R)` but true for `(not A) or (not R)`.
Day 3: authorization without reservation is `A and (not R)`; both compared
expressions happen to be true at FT, so that one test cannot distinguish them.

Day 4 outputs: `True`, `False`, `"unknown"`, `"unknown"`, then `ValueError`.
Python considers a nonempty string truthy even if its letters spell “false”;
the supplied function rejects that type instead of guessing its meaning.

Independent: `M or D`, table FTTT. Negation `not (M or D)`, table TFFF,
means neither defect is present. At M=true, D=false, the whole negation is
false while `(not M) or (not D)` is true. An unperformed duplicate check is
unknown; it is not evidence that D=false. Accept a documented conservative
policy to hold for review rather than declaring the record clean.

Delayed: `C and (not V)`, table FFTF. “Not verified” describes missing
verification, not proof that the citation's contents are false.

Score the four independent tasks on correctness and reasoning, two points
each. A provisional instructional progression decision requires at least 6/8,
correct whole-expression negation, and an explicit distinction between unknown
and false. These are draft teaching criteria, not validated mastery scores.
Reteach the specific failed concept and use a fresh rule; retain first-attempt
and assisted evidence separately. Use delayed performance before claiming
retention.

Homeschool/co-op: a parent or educator leads the short models and conference.
Charter/pod: group model, paired supported practice, then individual checks.
Budget an estimated 10m preparation plus 10m/day interaction/checking and 5m
delayed scoring; this estimate is not measured staffing evidence.

Copyright 2026 Agnus Dei Technologies, LLC. Original Bede lesson and code,
all rights reserved. The external Python documentation retains its own license.
Authored review draft; no independent academic approval, factory promotion,
pilot, publication or live activation is claimed.
