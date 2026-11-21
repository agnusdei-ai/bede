# An affordable open-weight path for Bede (plan, not built)

**Status: proposal for owner review.** Nothing here is implemented, downloaded
or measured. It is separate from #875 (voice) and #897 (installer voice). It
adds to the completion plan; it does not replace `docs/LDC_DEPLOYMENT.md`
(donated server hardware) or `docs/DECISIONS.md` entries 20 and 43.

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

- `docs/CAPACITY.md` measured the stack with a stub model: the shipped database
  pool (5 plus 5) supported 8 browser sessions and **failed at 10**, because a
  lesson turn holds its connection for the whole streamed reply. A raised pool
  (20 plus 20) passed 10. So the household target already fails on the shipped
  defaults, before any real model is involved. The API runs one process by
  design, which is a separate ceiling to measure at 30.
- The capacity harness steps real browser sessions to 10 and API clients to 64.
  It needs extending to a 30-user school profile, the arrival patterns above,
  the two-hour soak, per-user reporting and the overload steps. Its pass rules
  (zero 5xx, no dropped or duplicated answers) already match the zero-loss
  requirement.
- `docs/LDC_DEPLOYMENT.md` sizes 5 to 12 concurrent on 64 GB RAM plus a 12 to
  16 GB GPU, and 12 to 25 on a 24 GB GPU, assuming a third of enrolled users are
  generating at any moment. The new targets count users actively performing
  tasks, so those tiers cannot be reused without re-measurement, and that
  hardware is not "ordinary". This is the capacity-versus-cost conflict below.

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

Not in scope: the demo, the reference voice, any change to #875 or #897, a new
default model, or a hardware support claim without a measurement.
