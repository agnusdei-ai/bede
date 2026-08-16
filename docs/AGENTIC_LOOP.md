# A self-repairing loop you can trust

**A portable recipe.** Copy this file into your own repository, fill in the
two marked blocks, and you have an unattended loop that detects when your
product is broken for a real user, proposes a repair, and tells you what it
found. Nothing in it is specific to this project.

It is written for someone standing up their own loop in their own sandbox,
under their own rules. Every rule below has a real failure behind it, most
of them from a single bad day (2026-08-04) where a public demo was down for
hours while every dashboard read green.

---

## The claim this document is making

Most "autonomous agent" setups are three things: a **harness** (something
that runs the agent), **instrumentation** (logs), and **infrastructure**
(CI, secrets, schedules). Those are necessary and they are not agency. An
agent with only those will confidently do the wrong thing on a schedule.

Agency is the other seven components below. They are what make an
unattended change *trustworthy* rather than merely *automatic*.

| | Component | The question it answers |
|---|---|---|
| 1 | **Intent** | What outcome am I accountable for? |
| 2 | **Perception** | Can the failure describe itself? |
| 3 | **Attribution** | Do I actually know the cause? |
| 4 | **Authority** | What am I permitted to change? |
| 5 | **Verification** | Did I prove it, or assume it? |
| 6 | **Restraint** | Is doing nothing the right answer? |
| 7 | **Disclosure** | What do I owe the human? |
| 8 | **Escalation** | When must I stop? |
| 9 | **Memory** | Will the next run know what this one learned? |
| 10 | **Self-limitation** | Can I weaken my own limits? |

---

## 1. Intent — state the outcome, not the task

Give the agent the *user-visible* outcome it owns: "a visitor can start a
session." Not "make the check pass." An agent told to make a check pass
will, sooner or later, edit the check.

> **Rule:** the success criterion must be something a user experiences, and
> must be measurable without the agent's cooperation.

## 2. Perception — build failures that name themselves

Your agent can only act on what your system says about itself. Two lessons,
both learned expensively:

**Never let error handling destroy the diagnostic.** Our app caught a
precise browser error and replaced it with a friendly guess — *"the server
may be waking up"* — and logged nothing. The guess was wrong, the truth was
discarded, and hours went into the wrong layer. Friendly messages are right
for users. Log the raw error *before* substituting one.

**Instrument the boundary, not the call sites.** Wrap the outbound network
layer once rather than adding logging to thirty callers; a new caller can't
forget it. Record the *absence* of things too — a request logged as issued
with no matching response is itself a diagnosis (it means the request never
left).

**Listen for what the platform already tells you.** Browsers fire
`securitypolicyviolation` on every blocked request, naming the directive
and URI. Nothing in our app listened, so a policy bug looked exactly like a
network outage. Your platform almost certainly has an equivalent channel
you are ignoring.

> **Rule:** if a failure mode leaves no trace in your own logs, you do not
> have perception of it, and no amount of agent intelligence compensates.

## 3. Attribution — "I don't know" is a first-class output

The most dangerous thing this loop produced was not a missed failure. It
was a **confident wrong diagnosis**: the detector blamed a security policy
for an unrelated reason, while the true cause sat in the evidence being
ignored.

For a human reader that is merely misleading — they can push back. For an
unattended agent it is worse: it aims an automated change at the wrong
file, with a plausible justification attached.

> **Rules:**
> - Attribute narrowly. Match the *specific* signal to the *specific*
>   symptom, not "any error of this family."
> - Prefer the system's own reported cause over your inference.
> - Emit `cause: undetermined` rather than the most likely story. Then make
>   the agent's instructions treat `undetermined` as *investigate and
>   report*, never *act on the best guess*.

## 4. Authority — an allowlist, and a values list

Two different limits, for two different reasons.

**The allowlist is about competence.** Name the files the agent may edit.
Everything else is out of scope because the agent cannot verify the blast
radius. Keep it small enough to enumerate.

**The forbidden list is about values.** These are not "risky" files — they
are the files that encode what your product is *for* and who it protects.
In our case: the constitution governing the AI's conduct, authentication
and encryption, the moderation and child-safeguarding paths. An unattended
agent with commit rights over those is precisely the insider-compromise
surface the product exists to defend against.

**Tests belong on the forbidden list, always.** A failing test is a finding
to report, never an obstacle to remove. An agent that may edit tests will
eventually make a red build green by deleting the assertion, and will
describe that in the PR as a fix.

> **Rule:** the agent opens a pull request. It does not merge. Whatever
> human review your project requires is not suspended because the change
> came from a machine.

## 5. Verification — reproduce first, then prove

The bug that caused the outage shipped through a test that "passed." The
test had been written, observed to fail in a way the author didn't expect,
and then *adjusted to match the author's belief* about how the platform
behaved. The belief was wrong. The test then certified the bug.

> **Rules:**
> - **Reproduce the failure before fixing it.** If you cannot make it fail
>   on demand, you cannot know you fixed it.
> - **Run a negative control.** Revert the fix; confirm your test fails.
>   A test that has never failed proves nothing.
> - **Never change a test to match an assumption.** If a test surprises
>   you, the test may be right.
> - **Verify at the same level the user experiences.** Component checks
>   said healthy throughout an outage that made the product unusable. Ours
>   was a `curl` of a health endpoint: no browser, so no policy evaluation,
>   no origin header, no CORS. Everything measurable was fine.

## 6. Restraint — doing nothing is a valid outcome

Make this explicit, or the agent will infer that it was deployed to make
changes and act accordingly.

> **Rule:** "I investigated, the cause is outside my authority, here is what
> I found" is a *successful* run. Say so in the prompt, in those words.

Corollary: when the cause is configuration outside the repository — a
hosting setting, DNS, a credential — the agent must report it, not code
around it. A workaround for a config problem hides the real cause and
becomes permanent.

## 7. Disclosure — report the run, not just the change

The human's question is "what did it catch," not "what did it change."

> **Every run reports:** what a user experienced; what the evidence showed;
> what changed and why that addresses it; **what could not be verified**;
> and anything noticed but deliberately not touched.

That fourth item is the one agents skip and the one that matters most.
Ours could not verify a deployment action from CI, and saying so plainly
is what let a human confirm it on the first real run instead of trusting a
silent assumption.

## 8. Escalation — name the stop conditions

Stop and report, do not proceed, when:

- the cause is undetermined
- the fix would touch anything outside the allowlist
- the same failure recurs after a previous automated fix (the diagnosis was
  wrong; repeating it will not help)
- more than one PR would be open for the same issue
- a test fails that you did not expect to fail

> **Rule:** cap it. One PR per run, and a circuit breaker after N
> consecutive failed repairs. An agent in a loop with a wrong model of the
> problem will produce N wrong PRs just as happily as one.

## 9. Memory — write findings where the next run reads them

An unattended loop with no memory relearns the same thing forever, and a
human re-reads the same discovery in every PR.

Put durable findings in the repository, next to the code they constrain —
a comment on the config line, a named test, a note in the prompt's "known
causes" table. Our prompt carries two traps that already caused real
incidents; the next run reads them before touching anything.

> **Rule:** if a run discovers something the next run needs, the run isn't
> finished until that's written down somewhere version-controlled.

## 10. Self-limitation — the agent may not edit its own limits

> **Rule:** the prompt file, the workflow that invokes it, and the values
> list are all on the forbidden list. **An agent that can edit its own
> constraints has none.**

This is also why the prompt should be a versioned file rather than a string
inside CI configuration: the part most worth reviewing should appear in a
diff.

---

## Wiring it up

```
schedule ──▶ detector ──▶ pass ──▶ (log and stop)
                 │
                 └──▶ fail ──▶ report (JSON) ──▶ agent ──▶ PR ──▶ human
```

**The detector** drives your product the way a user does and emits one
structured report — pass or fail — that the agent can read without scraping
logs. For a web product that means a real browser, not a HTTP client. Ours
loads the page, dismisses the consent gate, clicks the one button a visitor
clicks, and reads back the app's own diagnostics buffer.

**Test on the hardware your users actually have.** Emulate at minimum: a
small cheap Android phone (360×760 — a Galaxy A10 is a realistic school
device in a way a developer laptop is not), a tablet, and desktop. Small
viewports expose hidden controls and unreachable touch targets that no
desktop run will ever surface.

Be honest in the report: emulation matches viewport, user agent, DPR and
touch model — **not** the renderer, the memory ceiling, or WebView quirks.
It catches layout and input failures, which is most of them. It does not
entitle anyone to say "tested on an A10." Write "emulated."

**The agent** gets: the report, the allowlist, the forbidden list, a table
of known causes and where each is *actually* fixed, and the stop
conditions. Ours is `.github/agent-prompts/demo-repair.md` — copy its
shape.

**Secrets:** a dedicated, separately revocable API key, never shared with
another workflow, so spend is attributable and a leak is contained.

---

## Fill these in

> ### BLOCK 1 — Your non-negotiables
> Replace with the files and behaviours that encode what your product is
> for and who it protects. The agent may never modify these, and may never
> modify this block.
>
> - _e.g. the policy defining your system's conduct_
> - _e.g. authentication, encryption, credential handling_
> - _e.g. anything protecting a vulnerable user_
> - **every test, in every language, for any reason**
> - **this file, the prompt file, and the workflow that runs them**

> ### BLOCK 2 — Your allowlist
> The complete set of files the agent may edit unattended. If a fix needs
> anything else, it stops and reports.
>
> - _e.g. deployment headers / reverse-proxy config_
> - _e.g. the detector script itself, only to fix a false alarm — never to
>   silence a real failure_

---

## Before you turn it on

- [ ] The detector fails when you break the product on purpose.
- [ ] The detector *passes* when the product works (no flapping — an alarm
      that cries wolf gets ignored, which is worse than no alarm).
- [ ] Its report names a cause you agree with, or says `undetermined`.
- [ ] The agent cannot merge.
- [ ] The agent cannot edit a test.
- [ ] You have read the prompt end to end, as you would a contract.
- [ ] One PR per run, with a circuit breaker.
- [ ] The API key is dedicated and revocable.

## The honest limits

- **An unattended loop is a departure**, not a default. If your project
  requires deliberate human authorization for scheduled or privileged
  automation, this inverts that. Decide it explicitly and write down why.
- **It will not diagnose novel failures well.** It is strong on the classes
  you have already met and encoded, weak on genuinely new ones — which is
  exactly why `undetermined → report, don't act` is load-bearing.
- **It cannot fix what isn't in the repository.** Most real outages are
  configuration. The loop's job there is to name the setting, not to route
  around it.
- **It cannot replace the judgment about what should exist.** It maintains;
  it does not decide.
