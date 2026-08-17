# G04: Physical Safety of the Agent's Own Suggestions

## What it prevents

Every safety layer in a typical agent is pointed at the *user's* input:
moderation classifiers, safeguarding patterns, injection detection. None of them
look at what the agent itself proposes.

This gap is invisible until you audit for it, and it is real for any agent whose
domain legitimately involves the physical world: hands-on learning, home repair,
cooking, lab work, fitness, fieldwork, DIY, childcare. The agent suggests an
activity. The suggestion is well-intentioned, on-topic, and pedagogically sound.
It also involves a stool, or boiling water, or a craft knife, and the person
following it is eight years old, or alone, or has no idea which parts are the
dangerous ones.

There is a second failure inside the first, and it is the one worth reading this
file for. The first version of this guardrail shipped with a hazard list naming
only objects and environments: heights, fire, sharp things, water, and a single
instruction for handling a *user-proposed* risky activity: redirect them to a
safe alternative. That is correct for someone who wants to throw something out a
window. It is dangerously wrong for someone who proposes holding their breath as
long as they can, or seeing how long they can go without eating, or testing how
much pain they can stand, framed in every case as part of the task.

Object risk and self-directed bodily risk look identical in the request and
require opposite responses. A safe-alternative swap applied to the second one
substitutes a prop and continues cheerfully past what may be a distress signal.
This block forks them explicitly, and defaults to the safer branch when the
classification is ambiguous.

## The block

```text
<physical_safety>
Any time you suggest a hands-on or physical activity: in any subject or context
keep it to safe, ordinary actions using items already meant to be handled:
paper, pencils, blocks, books, everyday objects already within reach. Never
suggest anything involving heights (climbing, balconies, standing on furniture),
fire or heat, sharp or breakable objects, throwing or forceful impact,
electricity, water beyond a sink, or eating or drinking anything that is not
food.

If an activity would genuinely benefit from another person present: a kitchen
tool, anything outdoors, anything requiring real physical exertion: say so
plainly ("ask someone to help you with this part") rather than assuming
supervision you cannot see.

When the PERSON proposes something risky, even framed as part of the task, two
different kinds of risk need two different responses:

(a) Risk to an object or the environment: throwing something, climbing on
    furniture, playing with fire. Do not go along with it. Redirect warmly to a
    safe alternative that still accomplishes the same thing, without shaming
    them for asking.

(b) ANY activity targeting their own body in a way that could cause injury,
    pain, or distress: holding their breath, restricting food or water, extreme
    heat or cold exposure, testing how much pain they can take, or anything
    similar, however it is framed. This is never a "safer alternative"
    situation. Stop the task and use the escalation response in <escalation>,
    exactly as if they had said it outside any task context.

When in doubt about which of (a) or (b) a request is, treat it as (b). The safer
mistake is stopping a task that did not need to stop, not continuing one that
did.
</physical_safety>
```

## Adaptation notes

**Universal, not tiered.** Resist the instinct to relax this for sophisticated
users. Apply it identically at every level of expertise: a less experienced
person is *more* literal about a suggestion, never less, and a competent expert
loses nothing by being told a step needs a second person. If you tier
anything here, tier the tone, never the hazard list.

**Rewrite the hazard list for your domain; keep the shape.** The list above is
tuned for someone at a desk. A home-repair agent needs mains electricity, gas,
load-bearing structure, and working at height. A cooking agent needs oil
temperature, raw protein handling, and knife technique. A fitness agent needs
load progression, joint hyperextension, and heat. The transferable structure is:
*a concrete enumeration*, *a name-the-help rule*, and *the (a)/(b) fork with a
default*.

**Keep the "ask someone to help" instruction concrete.** "Exercise caution" is
not a safety instruction, it is a disclaimer. Name the specific step.

**This does not belong in your constitution.** It operationalizes a
constitutional rule (protect safety and dignity) in one specific direction. It
should be ordinary code and ordinary prompt text, revisable by normal review,
because you will revise it as you learn your domain's actual hazards. Putting
operational detail under founder-review change control makes the change control
itself an obstacle people route around.

**Check your tools too.** Where every tool is screen-based, this guardrail is
entirely about language rather than tool behavior. If one of your tools actually
actuates something physical, this block is necessary and not sufficient: that
tool needs its own preconditions.

## How to test it

- **String-pin the (a)/(b) fork.** Both branches, and the default clause. This
  is precisely the text a later editor "tightens" into one instruction, which
  silently reintroduces the original defect. Verify by deleting the (b) branch
  and confirming the test fails.
- **Assert it is unconditional.** A test that builds the prompt across every
  user tier, mode, and configuration and asserts the block is present in all of
  them. Guardrails acquire conditions during refactors.
- **Confirm the cross-reference resolves.** Branch (b) points at your escalation
  block; assert both appear in the same built prompt.
- **Evaluate the fork behaviorally.** Two small prompt sets: object risk and
  self-directed bodily risk: with different expected outcomes. A model that
  redirects both is failing in the way this file exists to catch, and it is the
  failure most likely to look like a pass on a quick read.
