# Threat Model Template

Fill this in before adopting controls. It is two to three pages, not a document
project, and its job is to make the rest of your decisions obvious.

**The non-goals section is the most valuable part.** A threat model without
explicit non-goals is a wish list, and every security claim you make is
unbounded, which means it is unfalsifiable, which means it is not a claim.

---

## 1. What this system is

Two or three sentences. What it does, who runs it, where it runs, who talks to
it.

> *Example:* An intake assistant, self-hosted inside a customer's own network,
> configured by an administrator and used by that organization's staff. No
> multi-tenancy: one deployment per customer.

## 2. Assets

What an attacker would actually want. Be concrete; "user data" is not an asset,
it is a category.

| Asset | Where it lives | Why it matters |
|---|---|---|
| | | |

Include assets that are not data: the ability to *speak in your agent's voice*
to a trusted user is an asset, and it is the one prompt injection targets.

## 3. Adversary classes

For each: capability, motivation, and what they get if they win. Include the
ones that are not attackers.

| Class | Can do | Wants | Gets if successful |
|---|---|---|---|
| Curious legitimate user | Anything a normal session allows | To see what happens | Usually nothing; occasionally a real finding |
| Hostile user | Same, deliberately | Bypass, extraction, harm to another user | Depends entirely on §4 |
| Compromised content source | Author text your agent retrieves | Speak in your agent's voice | Whatever your confinement decision allows |
| Malicious operator | Full config access | Repurpose the agent | Everything: accept this and say so |
| Network attacker | Observe or modify traffic | Credentials, content | |

**The curious legitimate user belongs in the table.** Most boundary-testing is
not an attack, and a design that cannot tell the difference will punish your
users. This is where you decide how much false-positive cost you will accept.

## 4. If an injection fully succeeds, what happens?

Walk it end to end, concretely:

- Is there a secret in the prompt? → *If yes, fix that first; it is a design
  problem, not a filtering one.*
- Can a tool result carry text authored outside your process?
- Can the agent take an action with side effects?
- Who reads the output?
- Does anything the agent writes get persisted and replayed later?

Your answers set your entire detection posture. If a successful injection yields
nothing, tune for very low false positives. If it yields an action with side
effects, that is your highest priority and the prompt library is secondary.

## 5. Non-goals

State plainly what you are **not** defending against, and why. Each one is a
decision, not an omission: write the reason.

> *Examples:*
> - **A malicious operator.** They control the configuration and the
>   credentials. No control here survives that, and pretending otherwise would
>   misrepresent what the other controls mean.
> - **Model-level jailbreaks yielding the system prompt.** Treated as public.
>   Nothing in it is secret, so leaking it costs nothing.
> - **Physical access to the host.** Out of scope for a self-hosted deployment.

## 6. Self-defeating mechanisms

The controls that could become the incident. This section catches more real
problems than the adversary table, and almost nobody writes it.

Ask of every control: **can this be triggered by an attacker to deny service to
a legitimate user?**

- A lockout an attacker can trip on someone else's behalf.
- A rate limit whose bucket a legitimate retry shares with an attack.
- A safety redirect frequent enough that operators disable it.
- A verification step that fails closed on a dependency you do not control.

> *Real example from the source system:* a burst of failed logins that trips an
> account lockout must not also rate-limit that same person's next call to the
> **recovery** flow meant to get them back in. Those needed separate buckets,
> and the need was invisible until this section was written.

## 7. What is already correctly segmented

Credit what holds, so a later reader does not "improve" it. If your untrusted
loop cannot reach external tools, write that down here: otherwise someone will
helpfully unify the two registries.

## 8. Where this document is used

Name the reviews that consult it: pull requests touching these paths, adding a
tool, adding a data field, changing a control. A threat model nobody consults
is a document, not a control.

---

## Review triggers

Re-read this document when you:

- Add a tool, especially one with side effects
- **Persist any text the model wrote or the user influenced**: the replay
  question
- Add a content source your users can influence
- Change who your users are, or add a population who cannot evaluate the output
- Expose an interface another model consumes (an API, an MCP server)
- Add a new prompt-building path
