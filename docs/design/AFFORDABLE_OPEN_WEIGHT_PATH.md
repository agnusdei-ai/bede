# An affordable open-weight path for Bede (plan, not built)

**Status: proposal for owner review.** Nothing here is implemented, downloaded
or measured. It is separate from #875 (voice) and #897 (installer voice). It
adds to the completion plan; it does not replace `docs/LDC_DEPLOYMENT.md`
(donated server hardware) or `docs/DECISIONS.md` entries 20 and 43.

## 0. Decisions in force (owner)

- Acceptance thresholds stand unchanged: household 10 and school 30 concurrently
  active users; at full supported load p95 first useful tutoring response at
  most 5 s, routine explanation completed 12 s, tool-driven activity ready 15 s,
  deterministic practice feedback 500 ms; 30 s routine-turn deadline including
  queueing, retries and tool round trips; two-hour sustained tests with zero
  lost or duplicated progress, cross-user disclosure, crashes or out-of-memory
  kills; and every earlier learning-quality, authorization, privacy,
  persistence and model-capability gate. **This document proposes no different
  threshold.** (The only wording difference from the first draft is that the
  4-second first-token figure was replaced by the 5-second one above, already
  shown in section 7.) These are requirements, not a statement that any model
  or hardware profile has passed.
- Hosted spending cap: **$0**. No model download, purchase, paid call, merge or
  deployment is approved. #875 stays held. #898 and #899 stay open, and no
  model choice becomes an installer default before it is qualified.
- Platforms are first-class from the start: Raspberry Pi 4, Mac mini and
  ordinary Windows hosts. A dedicated GPU or high-memory workstation is never
  the entry requirement. Bede's reference voice is unchanged, its cost is
  accounted separately, and Piper is not a cost shortcut.

## 1. The goal, and what it is not

An ordinary family computer (a recent Mac or a mid-range PC, no GPU server)
should be able to run Bede's tutoring locally at a quality Bede stands behind,
at no new recurring charge, **at the mandatory capacity targets in section 7**:
10 concurrently active users per household installation and 30 per school
installation. These targets replace the earlier one- and two-learner household
proposal. It is **not** "bring a GPU server", and it does not
get there by loosening what Bede is: the constitution, the sacred rules, the
Socratic method, the parent controls and the learner records stay exactly as
they are. If a model cannot carry them, the answer is a different model or a
different split of work, never a weaker Bede.

Fixed by existing owner decisions and kept here: OpenAI remains Bede's
reference voice (demo and installed); tutoring-provider independence (a family
chooses the tutor, adding voice never changes it); the demo is untouched; no
silent cloud use, provider substitution, download or new recurring charge.

## 2. What exists today (inspected)

| Area | Implemented | Evidence |
|---|---|---|
| Local adapter | One OpenAI-compatible client covers Ollama, vLLM, LM Studio. `resolve_local_only()` never falls back. Model name discovery from `/models` when unset; clear errors when it cannot. Reachability probe every 10 min when local is primary. | `services/adapters/openai_compatible_adapter.py`, `router.py`, `main.py` |
| Installer discovery | Hardware tier from VRAM or RAM (6 tiers). Default lineup Mistral AI / IBM, Qwen as explicit choice (and now a menu, #898). Pulls once, keeps the model on re-runs, writes `LOCAL_LLM_MODEL`. | `packaging/unix/install.sh`, `Setup-Bede.ps1`, entry 43 |
| Lesson execution | `stream_tutor_response` with a bounded tool loop (3 rounds, 6 calls), turn controller, Action Validator, deterministic safety gate. Two model calls per turn (moderation classifier, then tutor). | `services/ai_service.py`, `routers/tutor.py`, `docs/LDC_DEPLOYMENT.md` §1 |
| Context construction | Cached static block (constitution, sacred rules, stage guidance, up to ~26 notes) + per-subject block + tools block, rebuilt each turn plus history. | `_build_static_prompt`, `_build_subject_prompt`, `TUTOR_TOOLS` |
| Deterministic paths | K-2 Sound Time, Number Time, Map Practice (app builds the item, app checks the answer, app records evidence); Practice Coach packs (diagnosis and practice generation in code after reading); teacher-quiz scoring; work ledger; session planner (orders, never chooses). | `services/k2_practice/`, `services/practice/`, `services/lesson_planner.py` |

## 3. What remains for an ordinary-computer experience

Ranked by how likely each is to be the first thing that fails. "Unverified"
means I could not confirm it from the repository and it must be measured.

1. **Context window (unverified, possibly blocking).** Today's prompt is far
   larger than a small default window, and nothing in this repository sets a
   context length for Ollama (no `num_ctx`, `OLLAMA_CONTEXT_LENGTH` or Modelfile
   anywhere). If the installed server's default window is smaller than Bede's
   prompt, the front of the prompt (constitution and rules) could be dropped
   silently. This must be tested first, on the exact Ollama version the
   installer provides, before anything else is concluded.
2. **Prompt size.** Re-measured now (characters, today's code): static block
   about 29.7k to 30.4k, subject block 7.3k to 11.4k (the largest subject
   previously measured was 14.6k), tools 27.0k (15 tools; `docs/LDC_DEPLOYMENT.md`
   measured 21.3k when there were 11). That is roughly 66k to 69k characters per
   turn before history; the earlier document converted a similar size to about
   16k tokens. Token counts here are unmeasured with any candidate's tokenizer.
3. **Prefill latency on small hardware.** Decode speed is not the binding
   constraint (10 tokens/s is already ahead of a child's reading); processing
   the large prompt every turn is. Whether the server reuses its cache across
   turns for the shared prefix on an ordinary computer is unmeasured.
4. **Two model calls per turn.** The moderation classifier runs first, on the
   same local model, and fails open. A small model that classifies badly removes
   a safety layer silently. The deterministic safeguarding regex still runs, but
   it is not a substitute.
5. **Tool calling by small models.** Fifteen tools, several with required
   fields and one whose ids must come from a supplied list. Entry 20 names this
   the likeliest failure for small models.
6. **No application-driven routine practice for grades 3 to 12.** K-2 has it.
   For older grades, routine drill (math facts, spelling, vocabulary, Latin
   vocabulary) is done by the model in dialogue, so every practice turn costs a
   full model turn. Practice Coach is parent-approved printed practice, not an
   in-lesson loop.
7. **Photo reading needs a vision-capable model.** Practice Coach reads
   photographed quizzes; the small text models in the installer lineup cannot,
   so on an ordinary computer that feature needs a separate, explicit decision.
8. **Concurrency and cost are unmeasured.** No per-session cost or memory
   figure for local execution exists; `docs/CAPACITY.md` measures the server,
   not a model.
9. **A possible silent cloud route.** `BEDE_ADAPTER_ORDER` defaults to
   `local,anthropic`. A deployment that has both configured fails over to the
   cloud automatically. The installers write `local` only, so a family
   installed that way is not exposed, but the default and a hand-edited `.env`
   are. The intended behavior needs to be an explicit parent control, default
   off, with a plain message when the local model is unavailable (Bede keeps
   everything else working and says so, never a quiet switch).

## 4. Architecture: deterministic first, model for language

Principle: the model is reserved for tasks that need language. Everything that
can be decided, built or checked by code is, because it is cheaper, faster,
exactly repeatable and identical for every family.

| Task | Who does it |
|---|---|
| Choose the next practice item | Application, from approved content and the saved record |
| Build the item and its answer | Application (the existing K-2 builders, extended by grade) |
| Check an answer (numbers, choices, spelling against a word list, Latin vocabulary against the catalog) | Application, deterministic |
| Pace, order, break, time limits, progression | Application (existing planner, timers, Action Validator) |
| Safety gate (patterns) | Application; the classifier remains a second layer |
| Record evidence and the work ledger | Application |
| Socratic dialogue, a hint worded for this child, noticing a good idea | Model |
| Judging free-form narration against the rubric | Model, parent-visible result, never a grade |
| Session summary for the parent | Model |

Approved content only: items come from the reviewed catalogs and banks the
repository already ships, never from a model inventing a fact. The application
decides progression; the model may suggest, the Action Validator and the saved
record decide.

A **compact delivery profile** for small models is a proposal, tested rather
than assumed: the static block's constitution and sacred rules stay verbatim and
first; per-turn tools are limited to those the current subject can use; notes
that do not apply to this turn are not sent; history is windowed. A profile is
accepted for a model only if it is non-inferior to the full prompt on that
model under section 6, and a model that needs rules removed to fit is rejected.

**Learner data.** No response cache of any kind that can serve one family's
generated text to another. The only reusable thing is a prefix cache of text
that is identical for every family (the constitution and rules, placed first so
a shared prefix exists); anything containing a parent setting, a learner name or
history is per-family and per-session and never shared. Local execution has no
cross-family sharing by construction. A hosted arm must show per-tenant
isolation and no retention or training on data, in its own terms, before it is
measured at all.

## 5. Candidates (exact, small-model class; pinned at approval)

Project-listed first (`install.sh`, `Setup-Bede.ps1`, entry 43). Exact Ollama
tag, quantization and digest, plus the license text at that revision, are
recorded when a download is approved; the licenses below are what entry 43
states or what must still be confirmed, not a review.

| Candidate | Tier it targets | License status |
|---|---|---|
| `ministral-3:3b` | `gpu_small`, `ram16` | Entry 43 records Apache-2.0; confirm at pinned revision |
| `granite3.3:2b` | `ram_small` | Entry 43 records Apache-2.0; confirm |
| `granite3.3:8b` | `gpu5` | Entry 43 records Apache-2.0; confirm |
| `ministral-3:14b` | `gpu10` | Entry 43 records Apache-2.0; confirm |
| `qwen3:4b`, `qwen3:1.7b`, `qwen3:8b` | the explicit Qwen choice | Not yet reviewed in this repository |
| `mistral-small3.2:24b` | reference ceiling only (not an ordinary computer) | Entry 43 records Apache-2.0 |

Models users name themselves (the #898 menu) are out of scope until these
finish; they are measured with the same suite before any support is claimed.

## 6. Bounded evaluation (finite, no paid or download step until approved)

**Arms.** (A) Local execution on the hardware tiers the installer already
supports; measured on the owner-designated ordinary computers (for example a
16 GB Apple Silicon Mac and a mid-range PC), nothing assumed for others, at the
load points in section 7.
(B) Shared hosted open-weight inference: the provider and exact model are named
only after approval, because no such provider is listed in the project today.
No generic benchmark selects either arm.

**Fixed test set (small, versioned in the repository, sample records only):**

1. Tool-call suite: every tool at least 10 times across stages, including the
   `show_visual_aid` id list and malformed-argument cases.
2. Safety suite: moderation classification on a sample set of benign, borderline,
   self-harm and violence messages for K-12, run through the real pipeline.
3. Rules suite: the existing adversarial probes plus one probe per sacred rule,
   at least 100 turns in total.
4. Teaching-quality set: 12 scripted 20-minute sessions across stages and
   subjects (including Spanish), played against each candidate and, as the
   comparison, the full-prompt run on the same model.
5. Routine-practice set: the deterministic path versus the model path on the
   same items.

**Measurements per candidate, per arm:** educational quality (blind educator
rating plus the suites above), the latencies in section 7 at every load point,
peak memory with the API, database and transcription running, and total cost
per learning session.

**Cost per learning session** is one reference 20-minute block (about 15 to 25
turns, two model calls each). Local: amortized hardware (owner-supplied price
and years, divided by sessions per year) plus measured watts times time at the
local rate. Hosted: input and output tokens per call times the provider's
published price, with and without the provider's caching, plus the moderation
call. Report the formula, the inputs and the result; no recurring charge is
assumed or committed.

## 7. Mandatory capacity targets and acceptance (owner direction)

**Targets.** Households: up to 10 concurrently active users. Schools: up to 30.
"Concurrent" means users actively performing learning tasks (submitting
answers, in a tutoring exchange, writing, using a tool-driven activity), not
users who are signed in or have a tab open. A candidate qualified for one
learner is not thereby qualified for a household or a classroom.

**Required load matrix**

| Installation | Active-user test points | Full-capacity sustained test |
|---|---|---|
| Household | 1, 5, 10 | 10 users for two hours |
| School | 1, 10, 20, 30 | 30 users for two hours |

At every point the workload is a realistic mix: deterministic practice, tutoring
responses, tool-driven activities, progress writes and session resume. Each
point runs two arrival patterns: staggered activity, and synchronized
submission bursts from every user at once. Image paths (photo reading, where a
vision-capable model is supported) and voice paths are tested separately and as
part of the mix where they apply. No paid call is made to produce the evidence;
voice runs against a stand-in unless a paid call is separately approved.

**Thresholds, all measured under full load.** Time is measured from the user's
submission, so queueing counts.

- Warm first useful tutoring response: p95 at most 5 seconds.
- Routine hint or short explanation completed: p95 at most 12 seconds.
- Tool-driven activity ready: p95 at most 15 seconds.
- Deterministic practice feedback: p95 at most 500 ms.
- Routine-turn deadline: 30 seconds including queueing, retries and tool round
  trips.
- Zero lost or duplicated progress writes, zero cross-user data exposure, zero
  crashes, zero out-of-memory kills.
- Results are reported **per user and per workload as well as overall**, so an
  aggregate percentile cannot hide a consistently underserved learner.
- Unchanged from section 4 and the earlier proposal: zero sacred-rule or
  constitution failures, no missed self-harm or violence item, tool-call
  validity of at least 98% (95% correct), educator-rated quality non-inferior to
  the full prompt, peak memory at most 75% of RAM. These apply at full load,
  where batching and shorter context pressure are most likely to degrade them.
  (The 4-second first-token figure in the earlier draft is replaced by the 5
  seconds above.)

**Shared inference is allowed, mixing is not.** Users need not each have a model
instance: the implementation may share inference resources, batch and schedule.
It must not mix learner context between users (checked by an automated test
that plants unique markers per user and looks for any appearing in another
user's output or record), and must not move requests to a paid cloud service
silently.

**Overload test.** Above each supported limit (for example 12 and 36 active
users) excess demand must produce bounded, understandable handling: a plain
"Bede is busy, please wait" state with an honest wait, no crash, no lost or
duplicated saved work, and no harm to sessions already in progress. This is
additional to, and never a substitute for, passing at 10 and 30.

**Support claims.** A model, runtime, hardware class, context budget and
concurrency are qualified only as the measured combination. RAM or GPU-memory
detection alone never supports a "10 users" or "30 users" statement.

### 7.1 What the existing evidence already says

- `docs/CAPACITY.md`'s first run, with a stub model, found the shipped database
  pool (5 plus 5) supporting 8 browser sessions and failing at 10. **That was
  measured before a fix that has since landed** (a turn now hands its
  connection back before the model call), and `docs/CAPACITY.md` records the
  confirming stack run as pending. A stack run on current main has been
  dispatched to settle it; until it reports, the 10-user platform result is
  unknown rather than failing. The API runs one process by design, a separate
  ceiling to measure at 30.
- The capacity harness steps real browser sessions to 10 and API clients to 64.
  It needs extending to a 30-user school profile, the arrival patterns above,
  the two-hour soak, per-user reporting and the overload steps. Its pass rules
  (zero 5xx, no dropped or duplicated answers) already match the zero-loss
  requirement.
- `docs/LDC_DEPLOYMENT.md` sizes 5 to 12 concurrent on 64 GB RAM plus a 12 to
  16 GB GPU, and 12 to 25 on a 24 GB GPU, assuming a third of enrolled users are
  generating at any moment. The new targets count users actively performing
  tasks, so those tiers cannot be reused without re-measurement, and that
  hardware is not "ordinary".

### 7.1a Simulation of the concurrent paths (planning only, not a measurement)

`scripts/qualification/capacity/sim_profiles.py` models N actively learning
users sharing one inference server, exactly as the application runs a turn
(moderation call, then the tutor call; a tool activity has two tutor rounds),
with queueing counted from submission, the owner's thresholds applied per user,
and both staggered and synchronized-burst arrivals over two simulated hours. It
contains no learner content and shares nothing across users. Its inputs are
throughput numbers, each labelled `assumption` or `project_doc`; a profile
without a real measurement is reported NOT_MEASURED and can never be called
qualified from here. It says nothing about educational quality.

What decode speed a profile needs (prefill assumed 40 times decode, 8 slots,
batching efficiency 0.7; the worst of staggered and burst):

| Design lever | 10 users | 30 users |
|---|---|---|
| Full prompt, every item through the model | ~370 tok/s | ~980 tok/s |
| Code answers 50% of routine items | ~340 | ~670 |
| Shared constant prefix reused (90%) | ~96 | ~350 |
| Code 50% plus shared prefix 90% | ~80 | ~210 |
| Compact 6k-token prompt (assumed) plus both | ~60 | ~180 |

What it shows, to be confirmed by measurement:

1. **Prompt processing, not decode, drives capacity.** Reusing the identical
   constant prefix across turns is the largest single lever (roughly four times
   less throughput needed); coded practice and a compact profile help less
   but compound. A server that reprocesses the full prompt every turn needs
   throughput no ordinary computer has.
2. **The project document's CPU-class profile (8B, Q4, about 13 tok/s) fails
   both targets by a wide margin even with every lever**, and an assumed
   3B-class ordinary-computer profile does too. On these inputs a household of
   10 active users is not met by an ordinary CPU-only computer.
3. **The project document's mid-range GPU profile (14B, about 30 tok/s) comes
   close at 10 users and fails at 30.** It meets first-useful and hint
   latency at 10 but not the tool-activity threshold, because a tool turn is
   three serial model calls and 280 output tokens at that decode speed leave
   little room. At 30 users it fails clearly.
4. Therefore the 30-user school target is, on current evidence, a shared
   inference server question (section 7.2, alternatives 2 and 3), and the
   10-user household target needs the prefix-reuse and coded-practice levers
   before any hardware conclusion is drawn.

These figures use unmeasured throughput and an assumed batching efficiency;
they size the question and rank the levers, nothing more.

### 7.2 The capacity-versus-cost conflict (to be settled with measurements)

Nothing here is measured, so no profile is claimed. Plausibly, 30 users each
sending a tutoring turn with a prompt of the size in section 3 will not be met
by one ordinary computer, and 10 may not be either. Concrete alternatives to
evaluate, in this order, each against section 7's thresholds:

1. **Cut inference demand without cutting quality:** deterministic practice for
   routine items (section 4) so only genuine language turns reach the model;
   a shared constant prefix so the large common part is processed once, never a
   cache of anyone's content; the compact delivery profile.
2. **Shared inference inside the installation:** one inference server on the
   household or school computer (or a second computer the school already owns)
   serving all users with batching and queue scheduling; no new hardware
   purchase assumed.
3. **Approved shared hosted open-weight inference** with per-tenant isolation
   and no retention or training, behind an explicit parent or administrator
   choice, never silent, with its cost per session reported.
4. Only if none passes: bring the owner the measurements and the cheapest
   hardware that does pass, as a choice. Supported users are never silently
   reduced and the claim is never weakened to fit.

### 7.3 Installer implications

- Ask first: **household or school**. That selects the capacity target (10 or
  30) and the profile list.
- Recommend only a **qualified profile**: a measured combination of model,
  runtime, hardware class, context budget and concurrency. If this computer
  matches no qualified profile for the chosen target, say so plainly and offer
  the alternatives in 7.2 instead of installing something that will disappoint.
  Until measurements exist, the installer makes no 10- or 30-user statement.
- Keep the user's own model choice (#898) as an advanced path, labeled as not
  qualified for the target until it has passed the suite.

## 8. Sequence and what I need approved

1. Read-only: confirm the context-window behavior of the installer's Ollama
   version (item 1 above) on an owner machine. Needs an owner machine, no
   download of new models.
2. Build the fixed test set and the harness (extends `slm_pilot_probe.py` and
   `spanish_local_model_probe.py`); no models run.
3. Extend the capacity harness to the section 7 matrix (including the 30-user
   school profile, soak and overload steps) with a model stub, so the platform
   ceiling is known before any model runs. Fix the 10-user pool finding first;
   it is independent of the model.
4. Approve the exact pins and the downloads, then run arm A at every load
   point. Approve a hosted provider and a spending cap before arm B.
5. Bring the measurements back against section 7; only then decide what to
   implement (the deterministic practice extension, the compact profile, the
   parent cloud-fallback control).

## 9. Platforms and topologies (host support is not inference proof)

"Runs on the host" and "runs inference on the host" are different claims, and
this plan never lets the first stand in for the second. A deployment is
qualified as a complete topology: where each piece runs, measured together.

Each component can run on the **host** (the computer the family or school
installed Bede on), an existing **LAN service** (a computer already on the
network that runs the inference server), or an approved **managed endpoint**
(hosted open-weight inference; off by default; $0 cap today).

| Component | Pi 4 host | Mac mini host | Ordinary Windows host |
|---|---|---|---|
| Bede app, API, database, application-run learning engine (deterministic practice, progression, reviewed content, checking) | Host. ARM64. Memory is the limit (Pi 4 ships up to 8 GB); Docker stack footprint is unmeasured | Host (the pilot target) | Host, through Docker Desktop |
| Transcription of the child's speech | Unverified: local transcription competes for four weak cores; may need LAN or managed | Host (unmeasured at 10 or 30) | Host (unmeasured) |
| Moderation and tutoring inference | **LAN service or managed endpoint.** The project's own document already refuses a Pi 5 for same-host inference on memory, bandwidth and cores; a Pi 4 is weaker | Host *or* LAN: same-host capacity at 10 and 30 is unmeasured (section 7.1a suggests it is doubtful) | Host *or* LAN: unmeasured |
| Reading photographed work | Needs a vision-capable model: LAN or managed only | Same, if such a model is qualified | Same |
| Bede's reference voice | OpenAI speech through the family's own account | same | same |

Arm64 (Pi 4, Apple Silicon Mac mini) and x86-64 (Windows, Intel Mac) are
qualified separately: the same pinned model file is run by different runtime
builds, so a pass on one architecture says nothing about the other. The Pi's
arm64 container images have been verified under emulation, not on hardware
(`docs/LDC_DEPLOYMENT.md` 10.4).

## 10. One architecture: task contracts and role pairings

The learning engine owns every task that can be decided, built or checked by
code. A model is only ever asked to fill a **role** against a written **task
contract**, so any model that passes a role's qualification can fill it on any
supported platform, and no model is wired in by name.

| Role (task contract) | Input | Output | Who runs it | Budget |
|---|---|---|---|---|
| Progression, item choice, pacing | saved record, approved content | next item | engine (code) | instant |
| Item building and answer checking | approved item bank | verdict, evidence | engine (code) | 500 ms p95 |
| Reviewed content lookup | subject, week | verbatim reviewed text | engine (code) | instant |
| Safety patterns | child's message | block or pass | engine (code) | instant |
| Moderation classification | child's message | category | **small model** | inside 5 s first response |
| Socratic turn, hint wording | context, reviewed content | short reply, tool call | **model** (small where it qualifies) | 5 s first, 12 s done |
| Tool-driven activity | subject, record | structured activity | **model** + validator | 15 s ready |
| Narration assessment, session summary | child's narration | rubric, parent summary | **larger model** where a small one does not qualify | background |
| Image reading | photographed page | structured reading | **vision-capable model** | background |

A **pairing** is a set of exact models, one per language role, per
(architecture, runtime version, context budget). One pairing is recorded per
platform and topology, and it is qualified or not as a unit. A small model that
fails a role does not weaken the role: another model fills it or it moves to the
LAN service, and a feature is never removed to make a benchmark pass.
Learner text lives in the request for that learner only; nothing is cached or
shared across families or users.

## 11. Candidate matrix (reconciles #898 with the installer lineup)

Registry facts could not be read from this environment (`ollama.com` is not
reachable here), so exact digests, sizes and licenses are **not retrieved** and
are left to be captured from the registry manifest at approval time, then pinned.
Entries marked "entry 43" restate that decision's license note; none is a
license review.

| Candidate (exact tag) | In today's installer? | Source | License | Quant / digest / size | Tools, vision, English, Spanish | Memory, hardware profile | Requirement addressed |
|---|---|---|---|---|---|---|---|
| `ministral-3:3b` | Yes, tiers `gpu_small`, `ram16` | Ollama registry | entry 43: Apache-2.0 | to capture | to verify on the model card and by the tool-call suite | to measure; Mac mini 16 GB, Windows 16 GB | household 10, moderation and routine roles first |
| `granite3.3:2b` | Yes, `ram_small` | Ollama registry | entry 43: Apache-2.0 | to capture | to verify | to measure; 8 GB Windows, Pi 4 only as LAN client | household 10, moderation role |
| `granite3.3:8b` | Yes, `gpu5` | Ollama registry | entry 43: Apache-2.0 | to capture | to verify | to measure; Mac mini 16 GB or more | household 10 |
| `ministral-3:14b` | Yes, `gpu10` | Ollama registry | entry 43: Apache-2.0 | to capture | to verify | to measure; Mac mini 24 GB or more | household 10, school 30 (shared) |
| `mistral-small3.2:24b` | Yes, `gpu20`, reference ceiling | Ollama registry | entry 43: Apache-2.0 | to capture | to verify | to measure; LAN service | school 30 (shared), narration role |
| `qwen3:1.7b/4b/8b/14b/32b` | Explicit choice only (entry 43) | Ollama registry | not reviewed here | to capture | to verify | to measure | comparison arm |
| A user-named model (#898 option 3) | New in #898 | user's choice | user's | n/a | n/a | n/a | **Never recommended or defaulted; not qualified for any target** |

**#898 reconciled:** its recommended default is unchanged (the existing tier
lineup), so nothing new becomes a default. Qwen was already an explicit choice;
the user-named option is an advanced path and is not offered as a recommendation.
I am relabelling it in the installer as advanced, with no change to what runs by
default.

**Bounded experiment per candidate (not started; needs approval):**
pin and fetch once on the designated machine; run the fixed suites of
section 6 at 1, 5 and 10 active users (household) and, for LAN-service
candidates, 10, 20 and 30 (school); stop at the first of: a hard gate failure
(any sacred-rule, safety or invalid-tool-id failure), a latency threshold missed
at two consecutive load points, memory above 75% of RAM, or a crash. Each stop is
recorded as the finding; the candidate is not retried with relaxed settings.

## 12. The first read-only inspection (named and bounded, not yet run)

**Machine.** Not yet designated, so nothing is run. The owner names one machine
(for example the pilot Mac mini); candidates for separate inspections are the
Mac mini, an ordinary Windows host and a Pi 4.

**Purpose.** Establish what the installed runtime is *configured* to accept.
That is different from measuring *effective* context capacity, which needs
inference and is a separate approval. A configured limit alone says nothing
about teaching quality, latency or 10- or 30-user capacity.

**Commands (read-only; none loads or warms a model, starts a service, changes
configuration or makes an inference call; the server is queried only if it is
already running).**

- `uname -m`, the operating system version, CPU model and core count, installed
  RAM (`sysctl hw.memsize` or `/proc/meminfo`, `systeminfo` on Windows).
- `ollama --version`, and the values of only these variables if set:
  `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_KEEP_ALIVE`,
  `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_HOST`. Nothing else from the environment.
- If a server is already running: `GET /api/version`, `GET /api/tags` (names,
  sizes and digests of installed models), and `GET /api/show` for installed
  models (trained context length and parameter defaults as metadata). Not
  `/api/chat`, `/api/generate` or `/api/pull`.

**Not collected:** learner records, `.env` or any credential, model outputs,
network addresses beyond `OLLAMA_HOST`.

**Expected output:** a short report per machine: architecture, RAM, runtime
version, the configured context length and parallelism (or "unset, runtime
default"), and each installed model's trained maximum context. The question it
answers is whether the installer's runtime would accept a context as large as
Bede's prompt (roughly 17,000 tokens, section 3). If it does not, that is the
finding, and the next request would be to set it, as a separate approval.

## 13. Hosted evaluation: proposal skeleton (no spend approved)

- **Proposed provider:** Mistral AI's hosted API, because it is already one of
  Bede's adapters and its data flow is already described in
  `docs/VENDOR_DATA_FLOW.md`; the exact open-weight model endpoint and its
  per-token price must be read from the provider's current documentation, which
  is not reachable here, so they are **not stated**.
- **Terms to confirm before any request:** no training on the data, retention
  period, region, per-tenant isolation. Sample data only, no learner content.
- **Cost:** token volume is computable now (suite size times about 17,000
  prompt tokens per tutoring call, with and without the shared prefix); the
  dollar figure needs the price list. The request will be one finite total, not
  an allowance, and nothing runs until it is approved and the cap is raised
  from $0.
- **Enforceable controls:** a prepaid or hard-limit key at the provider with
  auto-reload off, the key held by the owner, an application-side cap that
  refuses further calls at the total, and a run log reconciled to the invoice.

## 14. Operating budgets (structure; no unmeasured number is stated)

| Line | Household | School |
|---|---|---|
| Host hardware | the computer already owned; any purchase is the owner's decision | the school's existing server or computer |
| Inference | local (electricity measured during the suites) or a LAN service already owned | the same, shared by up to 30 users |
| Managed inference | **off; $0** | off; $0 |
| Bede's reference voice (OpenAI speech) | the family's own account, usage-based, **accounted separately** | the school's own account, separately |
| Licence | per `docs/SELLING_BEDE.md` | per the school agreement |

A predictable budget means: a fixed amount known in advance, a hard stop at it,
no automatic recurring charge and no silent move to a cloud service when local
capacity is short. When capacity is short the learner sees a plain "Bede is busy"
state and the adult sees what to change.

## 15. Platform and pairing matrix (finite)

Nothing in "capacity" is measured yet; every cell is unverified.

| Platform | Topology | Pairing (roles) | Compatible | Execution location | Capacity (10 hh / 30 school) | Cost to run |
|---|---|---|---|---|---|---|
| Pi 4 (arm64) | App, engine, DB on host; inference on LAN service | Engine + candidate pairing on the LAN service | App stack: unverified on hardware | App on host; inference on LAN | unverified | LAN service's electricity; $0 managed |
| Pi 4 (arm64) | Everything on host | n/a | **Not proposed:** weaker than the Pi 5 the project already refuses for same-host inference | host | not claimed | n/a |
| Mac mini (arm64) | Everything on host | `ministral-3:3b` for moderation and routine turns, `granite3.3:8b` or `ministral-3:14b` for the rest, to be measured | Installer supports it | host | unverified at 10; doubtful at 30 on current simulation | owned hardware plus electricity |
| Mac mini (arm64) | App on host; inference on a second LAN machine | per qualification | unverified | host and LAN | unverified | owned hardware |
| Windows (x86-64) | Everything on host | as Mac mini, plus the 8 GB tier | Installer supports it | host | unverified | owned hardware plus electricity |
| Windows (x86-64) | App on host; inference on LAN | per qualification | unverified | host and LAN | unverified | owned hardware |
| Any | Approved managed endpoint | hosted open-weight model | needs approval; $0 cap | managed | unverified | finite approved total, voice separate |

The lowest-cost configuration that meets every gate will be the one recommended,
decided only from measurements; where none passes, the conflict goes to the owner
with the numbers and alternatives, and the product claim is not weakened.

Not in scope: the demo, the reference voice, any change to #875 or #897, a new
default model, or a hardware support claim without a measurement.
