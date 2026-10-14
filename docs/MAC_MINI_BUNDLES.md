# Bede Mac mini bundles — separately purchased hardware

**Status: hardware SKUs defined; local macOS inference and campus capacity
not qualified.** These configurations represent the startup's target
appliance products, not measured throughput or approved school capacity.

## Two Mac mini configurations

| Product | Apple configuration (2026) | Buyer scenario | Model status |
| --- | --- | --- | --- |
| Bede Classroom Mac mini | **M6**, 32 GB unified memory, 1 TB internal SSD | Homeschool labs and smaller teaching groups | Unqualified until exact model/runtime workload test |
| Bede Campus Mac mini | **M5 Pro**, 64 GB unified memory, 4 TB internal SSD | Campus-managed deployment, conditional on actual concurrent usage | Unqualified until exact model/runtime workload test |

These choices are supported in the latest Mac mini specifications.
The M6 offers a maximum of 32 GB and 2 TB, while M5 Pro can be
configured with 64 GB and a 4 TB SSD. The M5 Pro is the **Pro-class
configuration** appropriate to the requested higher memory tier,
despite M6 being a later-generation base-series chip.

Verified hardware reference: https://support.apple.com/en-us/128108
Apple product introduction: https://www.apple.com/newsroom/2026/09/the-new-mac-mini-and-mac-studio-are-available-today/

Memory and SSD cannot be assumed to be user-upgradeable later.
Order the target factory configuration before sale. Independent
hardware procurement, support and warranty terms must be disclosed;
do not imply Apple endorses Bede.

## Commercial packaging is NOT product entitlement

- Hardware is sold as an **optional, separate purchase** from any Bede
  software or organizational subscription.
- Bede software offers: $25 per learner **per month**, or **$3,500 per
  physical school location per month** for unlimited *enrolled learner*
  seats at that signed location. Every additional branch/location
  needs its own subscription and signed campus-location license.
- The campus location licensing path uses an **explicit Ed25519-signed
  unlimited-at-location claim and signed location identifier**;
  an arbitrary high numeric seat count is never used. Operator issuance
  requires a paid-through expiry and the destination host's matching
  BEDE_LOCATION_ID. Automated Stripe billing for this new SKU is not
  yet connected. Hardware SKUs never change authorization.
- **Unlimited registered learners is not unlimited simultaneous local
  model inference.** The campus appliance has no published concurrent
  tutor count until a real installed system meets the tested target.
- Locuto remains optional and governed by its separate group size
  limits. A school's class roster is not one Locuto messaging group.

## Mac-specific integration that must be qualified

The existing Bede Linux local deployment design discusses vLLM,
GPU offload, caching and an NVIDIA/Linux-oriented inference host.
That does **not** establish performance or even packaging equivalence
under macOS and Apple Silicon.

Before a pilot can be operated on a Mac mini:

1. Use a tested **macOS arm64-compatible** local inference runtime
   (e.g. a separately qualified llama.cpp Metal or MLX-backed
   OpenAI-compatible service). Pin runtime/model/quantization digest
   and check Bede's model adapters, structured outputs and real
   tool use across all tutoring subjects.
2. Validate the *serial* moderation plus tutor steps and the
   failure-closed handling of any offline safety classifier.
   The historical local-host guidance flags some moderation
   paths as failing open. A shipping school configuration cannot
   waive that risk.
3. Benchmark warm and cold first-token latency, subject switching,
   context-cache correctness, token generation, peak unified
   memory, and all background tasks (voice input, diagnostics,
   database backup, reports) together.
4. Connect tablets via properly restricted TLS-protected LAN access,
   not by opening a publicly reachable inference port. Use FileVault,
   supported OS security updates, correctly scoped adult MFA, and
   per-learner access checks. A campus LAN is not an authorization
   boundary.
5. Provide an external encrypted backup target, verify actual restore,
   and specify a UPS and recovery process. A 4 TB internal SSD is
   capacity, **not** backup protection.
6. Record the supported concurrent *active inference requests*.
   Sample idle/enrolled student count is not a legitimate proxy.

## Engineering qualification CLI

The non-invasive acceptance evaluator:

    cd homeschool-api
    python -m core.mac_bundle_qualification --sku classroom --evidence /path/to/measured.json
    python -m core.mac_bundle_qualification --sku campus --evidence /path/to/measured.json

Example **schema only**, not benchmark data or a proof of capacity:

    {
      "origin": "real_target_device_test",
      "hardware": {
        "manufacturer": "Apple", "family": "Mac mini",
        "chip": "Apple M5 Pro", "architecture": "arm64",
        "memory_gb": 64, "internal_ssd_tb": 4
      },
      "model_id": "<pinned-local-model-identifier>",
      "runtime_version": "<pinned-runtime-version>",
      "target_concurrent_sessions": 1,
      "observed_peak_concurrent_sessions": 1,
      "peak_unified_memory_fraction": null,
      "turns": [],
      "workflow_checks": {}
    }

The intentionally incomplete example must **fail**. Replace it with
sanitized actual measurements and evaluated workflow controls, never
invented numbers or children's raw utterances. The output provides
a per-check pass/fail report; it does not create a signed test
certificate or independently verify the operator's statements.

The preliminary, adjustable pilot engineering thresholds are:
at least 30 measured turns; p95 first token at most 10 seconds;
p95 complete turn at most 45 seconds; at most 1% failed turns;
peak unified-memory utilization at most 85%; and **all mandatory**
security, diagnostics and recovery checks passing. These are release
targets to validate with an educator, **not scientific evidence** that
a student learns more.

If the campus profile fails, reduce simultaneous admission,
change the chosen inference model/runtime, or design a tested
additional worker. Do not advertise one Mac mini as having a
schoolwide throughput guarantee without those results.

## Acceptance decision

**Before any campus-wide capacity claim** record the institution's
timetable-based peak active sessions, then run matching concurrent
cold-start, mixed-subject, warm-cache and background workload
scenarios on the exact sellable Mac. Ensure the inference integration
passes a qualified pedagogical fidelity rubric, including truthful
DIBELS source handling. Review the raw benchmark traces independently.

As of this initial hardware SKU change, there is **no physical Mac mini
measurement evidence in the repository**. All unit tests are synthetic
checks of the acceptance algorithm, and no schoolwide tutor-session
concurrency has been established.
