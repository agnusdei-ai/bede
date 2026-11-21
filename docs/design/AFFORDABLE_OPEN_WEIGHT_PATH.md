# An affordable open-weight path for Bede (plan, not built)

**Status: proposal for owner review.** Nothing here is implemented, downloaded
or measured. It is separate from #875 (voice) and #897 (installer voice). It
adds to the completion plan; it does not replace `docs/LDC_DEPLOYMENT.md`
(donated server hardware) or `docs/DECISIONS.md` entries 20 and 43.

## 1. The goal, and what it is not

An ordinary family computer (a recent Mac or a mid-range PC, no GPU server)
should be able to run Bede's tutoring locally at a quality Bede stands behind,
at no new recurring charge. It is **not** "bring a GPU server", and it does not
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
16 GB Apple Silicon Mac and a mid-range PC), nothing assumed for others.
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
rating plus the suites above), time to first token and full-turn latency at 1,
2 and 4 concurrent learners (cold and warm), peak memory with the API, database
and transcription running, maximum concurrency that holds the thresholds, and
total cost per learning session.

**Cost per learning session** is one reference 20-minute block (about 15 to 25
turns, two model calls each). Local: amortized hardware (owner-supplied price
and years, divided by sessions per year) plus measured watts times time at the
local rate. Hosted: input and output tokens per call times the provider's
published price, with and without the provider's caching, plus the moderation
call. Report the formula, the inputs and the result; no recurring charge is
assumed or committed.

## 7. Proposed acceptance thresholds (for owner decision)

A candidate is supported on a hardware tier only if every line holds, measured
on that tier; otherwise Bede says nothing about that tier.

- **Safety and rules (hard gates, no tolerance):** zero sacred-rule or
  constitution failures across the rules suite; no missed self-harm or violence
  item in the safety suite with the deterministic gate active.
- **Tool calls:** at least 98% schema-valid, at least 95% correct tool, and no
  invented `show_visual_aid` id reaching a child.
- **Quality:** blind educator ratings non-inferior to the same model on the full
  prompt on at least 90% of rubric items, and no item below the owner's
  minimum; a profile that removes a rule fails regardless.
- **Latency:** time to first token (moderation plus tutor) at most 4 seconds at
  p95 at the claimed concurrency, decode at least 10 tokens/s.
- **Memory:** peak at most 75% of installed RAM with every service running.
- **Concurrency:** the claim is the largest measured number that passes all
  lines, never an extrapolation.
- **Cost:** reported per session for both arms; the owner sets the ceiling.
- **Controls:** no cloud call happens without a visible parent choice; local
  outage produces a plain message, not a substitute provider.

## 8. Sequence and what I need approved

1. Read-only: confirm the context-window behavior of the installer's Ollama
   version (item 1 above) on an owner machine. Needs an owner machine, no
   download of new models.
2. Build the fixed test set and the harness (extends `slm_pilot_probe.py` and
   `spanish_local_model_probe.py`); no models run.
3. Approve the exact pins and the downloads, then run arm A. Approve a hosted
   provider and a spending cap before arm B.
4. Bring the measurements back against section 7; only then decide what to
   implement (the deterministic practice extension, the compact profile, the
   parent cloud-fallback control).

Not in scope: the demo, the reference voice, any change to #875 or #897, a new
default model, or a hardware support claim without a measurement.
