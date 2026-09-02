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

Single-board computers — the Raspberry Pi 5 above all — are the obvious
donated-hardware thought and are caught by the first rule here. §9 answers that
question in full, including the GPU add-on and what a Pi 5 *is* good for.

---

## 9. Single-board computers, and the Raspberry Pi 5 in particular

The obvious donated-hardware thought, asked directly, and worth answering in
full because §8's rules catch it only implicitly.

**Short answer: not as the inference host — including with a GPU add-on —
but it has a real job in this deployment, further down.**

### 9.1 Why the usual benchmarks mislead here

Almost every published Pi 5 LLM benchmark reports **generation** speed. Bede is
bottlenecked on **prefill**, because of the ~16k-token system prompt in §1, and
essentially nobody quotes that number. It is the difference between "slow but
usable" and "unusable".

One measured anchor exists: **TinyLlama-1.1B at Q4_0 reaches about 108 tok/s of
prompt processing on a Pi 5.** Prefill is compute-bound and scales roughly with
parameter count, which gives the following. **The 3B and 8B prefill figures are
scaled from that single anchor, not measured** — treat them as an order of
magnitude, not a benchmark:

| Model | Prefill (tok/s) | Cold 16k prompt | Subject switch (~13k) | Decode (measured) |
| --- | --- | --- | --- | --- |
| ~1.1B Q4 | ~108 *(measured)* | ~2.5 min | ~2 min | 10-18 tok/s |
| ~3B Q4 | ~40 *(scaled)* | **~7 min** | ~5 min | 4-6 tok/s |
| ~8B Q4 | ~15 *(scaled)* | **~18 min** | ~14 min | 0.7-3 tok/s |

Against §1's requirement of ≥10 tok/s decode, and against a child waiting for
the first sentence of a lesson.

### 9.2 The three disqualifications, in order of how hard they are to argue with

1. **Memory. 16 GB is the ceiling, and it is soldered.** The Pi 5 ships in
   1/2/4/8/16 GB LPDDR4X-4267 with no expansion. §8 already says to refuse
   hardware under 32 GB or unable to reach 64 GB, so **the Pi 5 is refused by
   this document's own rule** — not by a new one invented for it.
2. **Memory bandwidth. ~17 GB/s peak**, from LPDDR4X-4267 on a 32-bit bus.
   Decode speed *is* memory bandwidth (§2), and this is roughly a tenth of the
   dual-channel DDR4 a donated server has. It is why an 8B model has a
   theoretical ceiling near 3.5 tok/s here and measures 0.7-3.
3. **Four cores, and Whisper wants some of them.** There is no usable
   accelerator on the base board: neither llama.cpp nor Ollama can use the
   VideoCore VII GPU for matrix work, and the AI HAT+ (Hailo) is a vision NPU,
   not an LLM decoder. §7 already warns that transcription competes with the
   language model for cores; on four cores total that stops being a tuning note
   and becomes the design.

The one configuration that clears the decode bar — a 1-3B model — is exactly
the size at which `docs/DECISIONS.md` entry 20's risk is sharpest: eleven tools
with required fields, a constitution-bearing prompt, and a fail-open moderation
classifier. A model that fits comfortably on a Pi 5 is a model this project has
the least confidence can be Bede.

### 9.3 The GPU add-on: it genuinely works, and still is not the answer

This has been demonstrated, and one part of it is counterintuitive in the Pi's
favour, so it deserves better than a dismissal.

**What works.** With Pi OS 13, an ARM64 NVIDIA driver and *patched* open-source
kernel modules, workstation cards on the Pi's PCIe link are recognised by
`nvidia-smi` — power, temperature, memory — and llama.cpp with Vulkan has run
3B models on them.

**And the single PCIe lane is not the problem people assume.** Once weights are
resident in VRAM, inference barely touches the bus: PCIe bandwidth matters for
loading the model (slow, once) and for streaming tokens (trivial). A Pi 5 with
a real GPU would have good prefill *and* good decode.

**Why it is still the wrong build:**

* **It is a patched, unsupported stack.** The stock driver expects x86-style
  memory management and crashes on arm64; the Pi 5 defaults to a 16 KB kernel
  page size against the driver's expected 4 KB, requiring a switch to
  `kernel8.img`. Published accounts describe this as worthwhile for
  experimentation and explicitly not for predictable production support.
* **The Pi cannot power the GPU.** That is a second, separate PSU.
* **The cost stack lands in the same place as a supported machine.** Pi 5 16 GB
  plus a PCIe adapter plus a used GPU plus an ATX supply is within noise of a
  used small-form-factor x86 desktop carrying the same GPU — which needs no
  patches, has 4 KB pages and stock drivers, and takes 64 GB of expandable RAM.
* **§8's last rule applies with full force**: a machine that cannot be repaired
  or supported in the country it runs in is a deployment with an expiry date.
  A configuration whose upstream describes it as experimental is worse than
  that, because the failure will not be a part you can replace.

### 9.4 If the deployment must be ARM and low-power

**NVIDIA Jetson Orin Nano Super**, about $249: 8 GB LPDDR5 at **102 GB/s** —
roughly six times the Pi 5 — with CUDA and a vendor-supported stack (JetPack)
rather than patched kernel modules. Measured LLM throughput in the 16-27 tok/s
range depending on power mode, at 7-25 W configurable, idling near 4.5 W. That
clears §1's decode bar with margin, and CUDA prefill makes §2's cold-start
problem disappear.

Its constraint is the **8 GB**, which caps model size and KV cache — so it is a
Tier A box in §4's terms, not a Tier B one. `docs/DECISIONS.md` entry 20 still
applies to whatever model is chosen for it.

An RK3588 board (Rock 5B, Orange Pi 5 Plus) sits between the two on bandwidth
and offers up to 32 GB, but its NPU is not a general LLM accelerator and the
software stack is less settled than either the Pi's or the Jetson's.

### 9.5 Where a Raspberry Pi 5 does belong here

**As a client, not a server** — and this is a real answer, not a consolation.
Bede's architecture is one server plus tablets over the LAN (§7). Where tablets
are unaffordable or hard to replace, a Pi 5 with a touchscreen is a legitimate
learner station: it needs only a browser, and browser-side text-to-speech runs
on the device at no server cost.

Two things to check before committing to that: the station needs **a real
microphone** — narration and voice verification are not optional in this
product — and browser speech synthesis should be confirmed working offline on
the actual image, per §11's open item on local text-to-speech.

A Pi 5 is also perfectly capable of running Caddy, nginx and PostgreSQL. But
splitting those onto a second box buys little: they are §3's small resident
costs, and the inference host has to exist regardless.

---

## 10. The Jetson Orin Nano Super, specified

Asked as "that's a solid price, and we can get peripherals donated by local
sponsors for the targeted schools." The price is genuinely good and the
donation model is sound. **The verdict is that it is the correct build for a
household or a single learner station, and is not a school server.** The
arithmetic below is why, and §10.3 says what a school actually needs.

### 10.1 The memory arithmetic, which decides it

Unified memory is the whole story. On a discrete-GPU box, the model gets its
own VRAM and everything else lives in system RAM. On a Jetson there is **one
pool**, and Bede's own stack draws from the same 8 GB the model does.

Published figure: **about 5.2 GB is available after the OS and JetPack
overhead**, roughly 2.8 GB consumed. From that 5.2 GB, subtract this
application (§3's table, all of it now resident in the same pool):

| | |
| --- | --- |
| Available after JetPack | **~5.2 GB** |
| API container (`torch` for `resemblyzer`) | −1.0 to 1.5 GB |
| PostgreSQL | −0.5 GB |
| `faster-whisper`, `base` int8 | −0.2 GB |
| Caddy + nginx | −0.2 GB |
| **Left for model weights + KV cache** | **~2.8-3.2 GB** |

Against §3's weight table and a ~16k shared prefix:

| Model | Weights (Q4) | KV left | Concurrent learners |
| --- | --- | --- | --- |
| ~3B | ~1.8 GB | ~1.0-1.4 GB | **1, maybe 2** |
| ~4B | ~2.4 GB | ~0.4-0.8 GB | 1, tight |
| 7-9B | ~5-6 GB | — | **does not fit** |

The shared 16k static prefix alone is ~1.0 GB at fp8 (§3). So a 3B model leaves
almost nothing for a second learner's own context.

**One to two concurrent learners places this at the bottom of Tier A** — a
household box, not the 5-12 concurrent Tier B a school needs. And the model
size it permits (≤3B) is exactly where `docs/DECISIONS.md` entry 20's
tool-calling risk is sharpest: eleven tools with required fields, against a
constitution-bearing prompt, with a fail-open moderation classifier on every
turn.

### 10.2 What it is genuinely good at

Everything above is a capacity finding, not a dismissal. On its own terms the
Orin Nano Super is the best answer in §9.4 for a reason:

* **102 GB/s** of LPDDR5 — about six times a Raspberry Pi 5, and enough that
  decode is not the constraint.
* **CUDA on a vendor-supported stack** (JetPack), not patched kernel modules —
  §9.3's objection to a Pi eGPU does not apply.
* **CUDA prefill makes §2's cold-start problem disappear.** This is the single
  biggest practical difference from any CPU-only box in this document.
* **7-25 W configurable, ~4.5 W idle**, measured 16-27 tok/s depending on power
  mode — comfortably past §1's 10 tok/s bar.
* Fanless-capable, sealed, no moving parts. In a dusty, hot, intermittently
  powered room that is worth more than a spec sheet suggests.

**As a sponsor-donation unit it fits well**: cheap enough to donate in
quantity, one per family or one per classroom station, and its power draw makes
§6's electricity arithmetic a rounding error rather than a running cost.

### 10.3 What a school actually needs, and the price shock

The smallest Jetson that is a school server is the **Orin NX 16 GB**. Note
carefully what it does and does not buy: its memory bandwidth is **also
102 GB/s**, identical to the Nano Super. Since decode speed *is* bandwidth
(§2), an NX is **not faster per learner** — it is *bigger*, which is the thing
that was actually short. ~13 GB usable holds a 7-9B model with real KV headroom,
or a 3B with room for a class.

**The price has moved against this.** Orin NX 16 GB is $599 MSRP for the
module, with third-party developer kits historically $650-900 — but NVIDIA
raised Jetson module and devkit prices by **up to 101% in July 2026**, with
current expectations in the $700-1,500 range. Confirm live pricing before
budgeting; this is the fastest-moving number in this document.

At that price the comparison changes:

| Build | ~Cost | Concurrent | Power (8h × 22d) |
| --- | --- | --- | --- |
| Orin Nano Super 8 GB | ~$249 | 1-2 | ~4 kWh/mo |
| Orin NX 16 GB | ~$700-1,500 | 5-10 | ~5 kWh/mo |
| Used SFF x86 + used RTX 3060 12 GB + 64 GB | ~$450 | 5-12 | ~35 kWh/mo |

**The x86 build wins on capital cost and loses on power.** At Philippine-typical
tariffs the ~31 kWh/month difference is roughly $6-7/month, near $80/year, so
about $240 over three years. That closes the gap against an NX at $700 and does
not close it against one at $1,400.

**One factor cuts the other way, and §8 already states it**: a machine that
cannot be repaired in the country it runs in is a deployment with an expiry
date. A used x86 desktop can be fixed anywhere with commodity parts. **A dead
Jetson is an RMA to another continent.** For a donated school deployment with
no budget line for replacement, that is a real argument for the boring x86 box,
whatever the electricity costs.

### 10.4 The blocking unknown: nothing has ever run Bede on arm64

**No CI job in this repository builds or tests for arm64.** Every runner is
`ubuntu-latest` on x86-64, `production-regression.yml` included — the workflow
whose whole purpose is proving the Docker stack really boots. So the claim
"Bede runs on a Jetson" is **entirely unverified**, and three specific things
in the image are known to be architecture-sensitive:

1. **`homeschool-api/Dockerfile` installs `torch==2.13.0` from
   `download.pytorch.org/whl/cpu`** — an index chosen deliberately to avoid
   pulling the CUDA-bundled build into a CPU-only container. On a Jetson that
   reasoning inverts, and the wheel required is NVIDIA's own Jetson build, not
   this one.
2. **`webrtcvad` already compiles from source** — the Dockerfile installs `gcc`
   and `python3-dev` precisely because it has no prebuilt wheel. A second
   architecture is a second chance for that to fail, and it failed once already
   on x86 (see that file's own comment: it was not caught until the image was
   first built end to end).
3. **`ctranslate2`, behind `faster-whisper`**, is the other compiled
   dependency, and it is on the voice path — the one a child notices first.

This is cheap to resolve and must happen **before any purchase**: build the
image for `linux/arm64` and boot the stack once. Either it works, or it names
its own problem. Buying hardware first and discovering this afterwards is how a
donated deployment becomes shelfware.

### 10.5 Peripherals worth putting on a sponsor's list

Since local sponsors are the funding model, the list should be a list. Per
deployment:

| Item | Note |
| --- | --- |
| **UPS** | Not optional — §6. Size for clean shutdown, 10-15 min at load. |
| **Learner devices** | Tablets, or Pi 5 + touchscreen per §9.5. |
| **A real microphone per station** | Narration and voice verification are core, not accessories. Built-in tablet mics are usually adequate; verify in the actual room. |
| **Gigabit switch + a decent WiFi access point** | No internet needed for a lesson. |
| **NVMe SSD** | For the Jetson, via its M.2 slot — do not run from an SD card. |
| **Active cooling** | Sustained LLM load is not the duty cycle a passive case is specified for. |
| **Surge protection** | Cheap, and the failure it prevents is total. |
| **A monitor, keyboard and mouse** | Setup only; one set can serve many deployments. |

### 10.6 Recommendation

1. **Buy Orin Nano Supers for households and single learner stations.** At $249
   with ~5 W idle they are the right unit for that job and the right thing to
   ask a sponsor to fund in quantity.
2. **Do not buy them as school servers.** One to two concurrent learners is a
   household, and a ≤3B model is entry 20's risk at its sharpest.
3. **For a school, price an Orin NX 16 GB against a used x86 SFF with a used
   12 GB GPU**, and decide on repairability as much as on cost — §8's rule
   points at the x86 box, §6's points at the Jetson.
4. **Before any of it, do §10.4.** One arm64 build, one boot. It is an
   afternoon, and every purchase above depends on the answer.
5. **A school deployment is still gated on `docs/DECISIONS.md` entry 21.**
   Hardware does not unblock multi-family administration.

---

## 11. What is not built yet

Stated here rather than discovered in the field:

1. **Prompt-cache warm-up (§2).** No code warms the static or per-subject
   prefix. On CPU-only hardware this is the difference between a good first
   impression and a bad one.
2. **An arm64 build of the stack.** Nothing in CI builds or tests for it —
   every runner is x86-64, `production-regression.yml` included — so no Jetson,
   Pi, or other ARM deployment in this document has ever been verified to run
   at all. See §10.4 for the three architecture-sensitive dependencies, and
   `docs/DECISIONS.md` entry 23. This blocks every ARM purchase in §9 and §10.
3. **A model evaluation** against Bede's real tool set and constitution —
   `docs/DECISIONS.md` entry 20. `scripts/adversarial_probe.py` already runs
   against a configurable adapter and covers part of it.
4. **Multi-family administration.** Every deployment today assumes one family
   with one parent credential. A parish server serving several families is
   `docs/DECISIONS.md` entry 21, and is **not** reachable by adding students to
   one pod — that would put each family's records in reach of the others.
5. **Local text-to-speech.** Bede's voice output currently uses the browser's
   own speech synthesis (on the tablet, so no server cost) or OpenAI's API. The
   browser path works without internet on most platforms; verify it on the
   actual tablets before promising it.
