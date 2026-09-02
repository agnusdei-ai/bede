# Deploying Bede on local hardware

For deployments where Bede's model runs **on the premises** — a repurposed or
donated Linux server serving tablets over the LAN, with no cloud model
provider and no per-token cost. `docs/DECISIONS.md` entry 19 records why this
is the shape for less-developed markets; this document is the arithmetic behind
the hardware.

**Read `docs/DECISIONS.md` entry 20 before buying anything.** The tiers below
size *memory and throughput*, which is deterministic and can be stated
honestly. Which model is actually good enough to *be* Bede has not been
measured by this project, and a spec naming a model nobody has run is a spec
that will be wrong in the field, where nobody can fix it.

---

## 1. What Bede actually asks of a model

Everything below follows from four properties of this application. The first is
measured against the real code; the rest are read off it.

### The system prompt is large, and it is the dominant cost

Measured 2026-09-02 by building the real prompt (`_build_static_prompt` +
`_build_subject_prompt` + `TUTOR_TOOLS`) for three grade stages, taking the
largest subject block:

| Grade stage | Static block | Largest subject block | Tools | Total |
| --- | --- | --- | --- | --- |
| K-2 `foundations` | 29,341 ch | Greek, 13,213 ch | 21,316 ch | **~16.0k tokens** |
| 3-5 `core_mastery` | 28,709 ch | Greek, 13,821 ch | 21,316 ch | **~16.0k tokens** |
| 6-8 `independent` | 29,777 ch | Greek, 14,594 ch | 21,316 ch | **~16.4k tokens** |

Add conversation history — a 20-minute subject block runs perhaps 15-25
exchanges — and a realistic per-turn context is **20k-24k tokens**. Size for a
**32k context window**. Reproduce the measurement with
`homeschool-api`'s own modules if the prompt grows; it has grown steadily.

### There are two model calls per turn, not one

`services/moderation.py`'s `classify_child_message()` runs on **every** turn
before the tutor sees the message, through the same adapter. Its prompt is
short, but it is serialised ahead of the tutor call, so its latency is added to
every turn. Budget for it.

It also **fails open**. On a local deployment that matters more than on a
cloud one: a model that classifies badly removes a safety layer and emits no
signal that it has.

### Output is short and streamed

`max_tokens` is 400 for a tutor turn (deliberately tight, for Mater Amabilis
brevity) and 600 for the once-per-session summary. A child reads at roughly
4-5 tokens/second, so **10 tokens/second of decode is comfortably ahead of
their reading**, and more buys little. This is the single most forgiving
requirement in the whole spec, and it is why CPU-only inference is viable here
at all.

### Tool calling is not optional

Eleven tools, several with required fields, one (`show_visual_aid`) whose ids
must come from a supplied list. This is the requirement most likely to be the
one a small model fails — see entry 20.

---

## 2. Why prefix caching is the whole ballgame

**Decode** is memory-bandwidth-bound: roughly `bandwidth ÷ bytes-read-per-token`.
**Prefill** is compute-bound: roughly `2 × active-params × tokens` FLOPs.

For a 16k-token prompt that difference is brutal on a CPU. A rough order of
magnitude: 16k tokens against 3B active parameters is on the order of 10^14
FLOPs, which a many-core server without a GPU will take **tens of seconds** to
work through. No child waits that long for the first sentence of a lesson.

Automatic prefix caching (vLLM's APC, or llama.cpp's prompt cache) removes
almost all of it, because Bede's prompt is *built* to be cacheable — the static
block is deliberately stable and is already marked `cache_control: ephemeral`
for the Anthropic path:

* The ~16k static prefix is computed **once** and reused by every session, every
  subject, every child, until the process restarts.
* Within a conversation the whole prior context is a prefix, so a steady-state
  turn prefills only the new message — tens of tokens.
* The expensive moments left are a **cold start** and a **subject switch** (a
  fresh ~13k subject block).

**Therefore, two non-negotiable configuration requirements**, and one
recommendation this project should implement:

1. Enable prefix caching on the inference server. vLLM: `--enable-prefix-caching`.
   llama.cpp/Ollama: keep the slot/prompt cache enabled and give it room.
2. Give the cache enough memory to hold the shared prefix plus every live
   session (§3).
3. **Warm the cache at startup for each enabled subject**, and again after
   midnight (the weekly/daily rotation catalogs change the subject block by
   date). This is not built yet. Without it, the first child of the day pays the
   full cold prefill and every subject switch pays a partial one.

---

## 3. Memory arithmetic

### Weights

At 4-bit quantisation (`Q4_K_M` or equivalent), weights are roughly
`0.6 GB per billion parameters`:

| Model class | Weights at Q4 |
| --- | --- |
| 7-9B dense | ~5-6 GB |
| 12-14B dense | ~8-9 GB |
| 27-32B dense | ~18-20 GB |
| 30B-A3B MoE (30B total, 3B active) | ~18-20 GB resident, **3B active per token** |

### KV cache — the part that gets forgotten

Per token: `2 × layers × kv_heads × head_dim × bytes`. For a modern
grouped-query-attention model this lands around **100-130 KB/token at fp16**,
or half that with fp8 KV.

Against a 32k window that is **3-4 GB for one sequence at fp16** — which sounds
fatal until prefix caching is accounted for. The ~16k static prefix is stored
**once and shared**, so the marginal cost of an additional concurrent learner is
only their own subject block and history:

| | fp16 | fp8 KV |
| --- | --- | --- |
| Shared static prefix (~16k tok) | ~2.0 GB | ~1.0 GB |
| **Per additional learner** (~8k tok unique) | **~1.0 GB** | **~0.5 GB** |

Use fp8 KV where the server supports it. It is a much better trade here than
quantising weights further.

### Everything else on the box

| Component | Resident |
| --- | --- |
| API container (`torch` imports at ~480 MB alone, for `resemblyzer`) | ~1.0-1.5 GB |
| `faster-whisper`, `base` model int8 (`whisper_model_size` default) | ~0.2 GB |
| PostgreSQL | ~0.5-1 GB |
| Caddy + nginx + OS | ~0.5 GB |
| **Non-model total** | **~2.5-3 GB** |

---

## 4. The tiers

Sized for **concurrent learners actually mid-turn**, not students enrolled. In
a real pod, children spend most of a session reading, narrating aloud, writing,
and on breaks. Assume roughly **one third of enrolled students are generating
tokens at any moment**, and never fewer than two.

### Tier A — Household or small pod · 1-4 concurrent · CPU only

| | |
| --- | --- |
| CPU | 8+ physical cores, x86-64 with **AVX2 minimum**, AVX-512 materially better |
| RAM | **32 GB minimum, 64 GB recommended** — DDR4 or better |
| Storage | 256 GB SSD (NVMe preferred; the model file is read constantly) |
| GPU | None |
| Model | 7-9B dense at Q4, **or** a small MoE |
| Expected | ~10-16 tok/s single stream on a dense 8B; slower under load |

Viable, and honestly the weakest configuration worth deploying. Decode sits
just above a child's reading speed with nothing spare.

### Tier B — Recommended · 5-12 concurrent

| | |
| --- | --- |
| CPU | 16+ physical cores |
| RAM | **64 GB minimum, 128 GB comfortable** |
| Storage | 512 GB NVMe SSD |
| GPU | **12-16 GB** (a used RTX 3060 12 GB or 4060 Ti 16 GB is the value point) |
| Model | 12-14B dense at Q4 on the GPU, or a 30B-A3B MoE with GPU offload |
| Expected | 30+ tok/s, and prefill fast enough that a cold subject switch is unremarkable |

**A GPU here is not about decode speed. It is about prefill.** Even a modest
one turns a cold 16k-token prompt from tens of seconds into roughly one, which
is the difference between "Bede is thinking" and "Bede is broken."

### Tier C — Comfortable · 12-25 concurrent

| | |
| --- | --- |
| CPU | 24+ physical cores |
| RAM | 128 GB |
| Storage | 1 TB NVMe |
| GPU | **24 GB** (RTX 3090 or 4090) |
| Model | 27-32B at Q4 entirely in VRAM, 32k context, fp8 KV |

---

## 5. The MoE recommendation, and why it suits donated hardware

Donated server hardware has a characteristic shape: **many cores, a great deal
of cheap ECC RAM, wide memory bandwidth, and no GPU.** A dense model wastes
that, because decode reads every parameter for every token.

A **Mixture-of-Experts model with a small active-parameter count** is the right
answer for exactly this hardware. A 30B-A3B model holds 30B parameters in RAM
(which a donated server has) but reads only ~3B per token (which is what decode
speed depends on) — roughly 8B-class decode speed at substantially better
quality.

`core/config.py`'s `local_llm_model` default is already an A3B MoE
(`Qwen/Qwen3-Coder-30B-A3B-Instruct`). Note that default was chosen as a
plausible self-hosted option and **has not been evaluated against Bede's own
tool set** — entry 20 again. Its *shape* is right for this hardware; whether
that specific coder-tuned checkpoint is the right choice for a Socratic tutor
is an open question, and a general-instruct sibling is the obvious thing to
measure against it.

---

## 6. Power is the constraint that surprises people

**This is the finding most likely to change a hardware decision, and it points
away from donated rack servers.**

A dual-socket rack server of the generation typically donated draws on the order
of **300-500 W** under light load. A modern mini-PC or single-socket desktop of
equivalent usable capability for Tier A draws **30-65 W**.

Over a school month (8 hours/day, 22 days), that is roughly **70-90 kWh versus
6-11 kWh**. Left running continuously it is ~290 kWh versus ~25 kWh.

At electricity tariffs typical of the Philippines — among the higher ones in
Southeast Asia — **the annual electricity cost of a "free" donated rack server
can exceed the purchase price of new, quieter, more efficient hardware that
does the same job.** Please verify the current local tariff before treating
this as decided; the physics is solid, the price per kWh is an assumption.

Practical consequences:

* **Prefer efficient hardware over free hardware** unless electricity is
  subsidised or donated too.
* **Power the server down outside school hours.** A boot takes a minute and
  saves two thirds of the bill. This also means §2's cache warm-up runs daily,
  which is another reason to build it.
* **A UPS is required, not optional** — for the brownouts and outages common in
  the markets this document is written for, and because PostgreSQL and an
  abruptly-cut model file do not enjoy losing power. Size it for clean shutdown
  (10-15 minutes at load), not for running through an outage.

---

## 7. The rest of the room

| | |
| --- | --- |
| Network | Gigabit wired switch to the server; a decent WiFi access point for tablets. **No internet needed for a lesson.** |
| Tablets | Any device with a modern browser and a microphone. `docs/DECISIONS.md` entries 15-16 cover the OS-version posture. |
| OS | Ubuntu Server LTS. Docker Compose per `docs/PRODUCTION_SETUP.md`. |
| Internet | Wanted for updates, licence renewal and feedback email — all asynchronous and none lesson-blocking. |

**Configuration worth changing from the defaults on Tier A:**

* `TRANSCRIPTION_PROVIDER=local` — already the default, and the only correct
  answer here.
* Consider disabling live partial transcription. `services/transcription.py`
  re-transcribes the whole growing buffer each pass; on a CPU already busy with
  the language model this competes directly. The **final** pass is never
  skipped, so what reaches Bede is identical — only the word-by-word preview
  is lost.
* `VOICE_TRANSCRIPTION_MAX_CONCURRENCY` stays at 1 unless you have cores to
  spare. Whisper is internally multi-threaded; overlapping passes thrash rather
  than parallelise.

---

## 8. What to refuse

A donation is only a saving if the thing works. Decline:

* **Under 32 GB of RAM**, or RAM that cannot be expanded to 64 GB.
* **DDR3-era platforms.** Memory bandwidth is what decode speed *is*, and these
  are roughly half of DDR4 while drawing more power.
* **CPUs without AVX2.** Inference runtimes either refuse them or fall back to
  paths several times slower.
* **A GPU with under 8 GB of VRAM.** It cannot hold a useful model plus KV
  cache, and splitting across host memory gives back most of the benefit.
* **Spinning disks as the only storage.** Model load times become minutes.
* **Anything you cannot get a power supply, fans, and drive caddies for
  locally.** A server that cannot be repaired in the country it runs in is a
  deployment with an expiry date.

---

## 9. What is not built yet

Stated here rather than discovered in the field:

1. **Prompt-cache warm-up (§2).** No code warms the static or per-subject
   prefix. On CPU-only hardware this is the difference between a good first
   impression and a bad one.
2. **A model evaluation** against Bede's real tool set and constitution —
   `docs/DECISIONS.md` entry 20. `scripts/adversarial_probe.py` already runs
   against a configurable adapter and covers part of it.
3. **Multi-family administration.** Every deployment today assumes one family
   with one parent credential. A parish server serving several families is
   `docs/DECISIONS.md` entry 21, and is **not** reachable by adding students to
   one pod — that would put each family's records in reach of the others.
4. **Local text-to-speech.** Bede's voice output currently uses the browser's
   own speech synthesis (on the tablet, so no server cost) or OpenAI's API. The
   browser path works without internet on most platforms; verify it on the
   actual tablets before promising it.
