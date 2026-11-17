# Bede: private inference and no-training architecture

> **Status: proposed target, not current behaviour.** This is the owner's
> assessment (2026-11-17), recorded as the plan of record for private
> inference. Every requirement below is a recommendation, not a completed
> change or a release approval. It is tracked as `docs/DECISIONS.md`
> entry 44. "What the code does today" at the end maps it to the current
> implementation.
>
> **References owed.** The assessment cites its sources as [1]–[25]. The
> numbered reference list was not supplied with it, so the markers are kept
> as written and the list is still owed. Until it is added, treat each
> provider-terms statement below as unverified here, and check it against the
> provider's current documentation before relying on it.

## Scope and assurance boundary

This assessment uses the deployment matrix supplied by Bede's owner as its working baseline. It does not independently verify the repository, deployed configuration, provider accounts or network controls. All implementation requirements below are recommendations, not completed changes or release approvals.

Three promises need separate controls: **no use for model training**, **no provider retention**, and **no transfer outside the family or school boundary**. Provider documentation distinguishes these: OpenAI excludes API data from training by default but describes retained abuse-monitoring logs; Mistral explicitly separates training opt-out from zero data retention (ZDR).[1][2]

For a strict no-external-transfer promise, the recommended architecture is customer-controlled inference with network-enforced egress restrictions. An external API, even under ZDR, receives the request to process it; ZDR is a retention arrangement rather than a no-transfer mechanism.[2][3][1]

"Not exportable" should mean **no unauthorized disclosure to a provider, tool, other tenant or outside destination**. It should not eliminate authenticated family or school access, authorized backups or legally required access/deletion processes. FTC guidance specifically describes school review and deletion opportunities when relying on school authorization under COPPA.[4]

## Recommended deployment policy

The following is a proposed target policy, not a description of current implementation.

| Deployment | Recommended inference route | External disclosure rule | Failure behavior |
|---|---|---|---|
| Ordinary homeschool | Customer-controlled local inference by default | No child/family records to cloud or external MCP in private mode | Explain local unavailability; no cloud fallback |
| Offline homeschool | Local inference under the existing offline topology | No external model, speech, OCR, embedding or tool processing | Remain offline; offer available non-model activities |
| School/charter | School-controlled, authenticated inference service | No cloud route or external MCP for protected records | Fail closed; alert the authorized administrator |
| Optional adult drafting | Separate stateless cloud workflow for public or sample material | No access to learner histories, rosters, private documents or protected conversation context | No fallback to an unapproved provider |
| Public demo | Cloud processing of sample/public examples | No connection to actual family/school datasets; clearly disclose cloud processing | Restrict unsupported inputs; do not claim local-only privacy |

The proposed adult-drafting exception is intentionally narrow. Parent or teacher status alone should not authorize sending everything that role can access. School consent under COPPA is limited to the authorized educational context and does not authorize unrelated commercial uses.[4]

A local service on another school machine can satisfy a school-controlled boundary without being loopback-only. However, its identity and authorization must be verified: NIST explicitly rejects implicit trust based only on LAN location or ownership.[5]

## Where the matrix needs strengthening

### Ordinary homeschool routing

In the supplied matrix, ordinary homeschool allows any local-adapter URL and live failover among external providers. Recommended change: resolve the privacy policy **before** selecting an adapter. In private mode, filter the eligible provider set to approved customer-controlled endpoints; ordering configuration must never reintroduce a disallowed provider.

Proposed invariant: **local service unavailable means unavailable, not permission to export the request**. A cloud exception, if offered at all, should be a separate operation with explicit scope rather than a transparent continuation of a protected conversation.

### Private addresses and local proxies

The school row's private-address restrictions are useful destination constraints, but are insufficient to establish the downstream data flow. NIST's zero-trust principle means that a private address alone is not proof of a trusted service.[5]

Recommended controls: approve the exact service identity, hostname, port and resolved destinations; authenticate school-LAN connections with TLS; reject redirects and unintended proxy use; verify the service is not forwarding to a cloud provider. Avoid treating every host in a private address range as authorized.

### Python-level restrictions

The supplied offline row describes a Python-level egress block. Keep that as application defense, but add OS/container/network enforcement covering the backend, model server, speech services, workers and native subprocesses.

Docker documents that containers normally have outbound connectivity and that internal networks restrict external access. It also documents relevant exceptions: a dual-connected service can retain internet access, and internal-network gateway/host services remain reachable in some configurations.[6][7][8]

Consequently, an internal network is a component of the design, not sufficient evidence by itself. Verify actual network membership, host routes and forwarding services on every supported platform.[8][6]

## Private inference implementation

### Separate downloads from operation

Recommended design: download approved model/runtime artifacts through a maintenance process that has no mounted learner database, document store or conversation logs. Verify provenance and hashes, then make artifacts available to the inference runtime. Do not open a general internet window in a process that also holds private data.

For Ollama, disable cloud features explicitly using `OLLAMA_NO_CLOUD=1` or its documented server configuration, restart the service and verify the effective setting. Ollama documents that this disables its cloud models and web search; the setting complements rather than replaces network enforcement.[9]

Choose model provenance and licenses deliberately, but do not use country of origin as the privacy boundary. The stronger boundary is the verified runtime, its accessible data, its privileges and its allowed network paths, consistent with resource-focused zero trust.[5]

### Keep inference separate from training

Recommended policy: production learner data must not feed fine-tuning, adapters, distillation, training datasets, provider feedback programs or automatic evaluation uploads. Keep approved model weights read-only where feasible, and omit training jobs from the production inference service.

Inference and training are distinct operations: Transformers documentation separates loading/using pretrained models from running a training loop that explicitly receives training data.[10][11]

**Owner ruling (2026-11-17): a local model is trained only under the supervision of Agnus Dei Technologies' authorized team.** Bede never trains, fine-tunes or adapts a model on its own, on any installation, and no family, school, parent, teacher or setting can start one. Training is a supervised act by that team, outside the running product. The ruling settles who may train; it does not by itself decide which data may be used. The rule above still holds for learner data: it is not used for training unless a separate decision says so, and the consent notices families and schools have accepted (`data/consent_notice.txt`, `data/school_data_notice.txt`) do not describe any such use.

Bede can still maintain a child's application-level practice history or skill estimate locally. The proposed distinction is between updating that authorized learner record and using it to update model parameters or contribute to an outside training corpus.

### Cover every modality

Recommended private-mode coverage includes chat, speech recognition, speech synthesis, OCR, embeddings, moderation, quiz extraction, drafting, retries and background processing — not just the primary language-model adapter.

For browser speech synthesis, select only voices reporting `localService === true`; MDN defines this property as distinguishing a local synthesizer from a remote service. Recommended fallback: device-local voice, otherwise an accessible non-speech path; if revealing a written word changes a phonics assessment, label it as an assisted activity or skip that item rather than record unaided evidence.[12]

For listening, do not assume "browser speech" means on-device recognition. MDN documents a separate `SpeechRecognition.processLocally` control and notes that its default is false. Any browser-based listening path therefore needs its own explicit qualification.[13]

## Model and tool access

Recommended design: the model receives only the minimum current-task context and has no direct learner database credentials, arbitrary SQL, unrestricted filesystem access, network fetch, email or export capability. The application authorizes each retrieval and tool call using the authenticated session's family, school, learner and role scope — not model-supplied identifiers.

OWASP advises that authorization and privilege separation must remain outside the model; instructions in a system prompt are not a security boundary. Its sensitive-data guidance also identifies disclosure through retrieved documents and accumulated conversation context, supporting retrieval-layer access controls and minimal context.[14][15]

For strict private mode, disable external MCP even in the parent workspace. If external research is later offered, put it in a separate public-material workspace without protected-record retrieval or inherited private history. MCP's own security guidance documents exfiltration, token-handling and SSRF risks; parent-only placement does not remove those technical risks.[16][17]

Recommended output handling: no automatic fetching of model-generated external image URLs, no unapproved external actions and no bulk export tool. Keep authorized owner/admin exports behind normal application authorization and audit controls. These are architectural restrictions intended to reduce the impact of prompt injection rather than a claim that prompt injection has been eliminated.[18][19]

## If cloud processing is required

Cloud can support a **restricted-processing/no-training** offering, but it must be described separately from **data stays within the family or school**. Provider ZDR documentation describes external processing followed by limited retention, with feature-specific scope and exceptions.[1][2][3]

| Provider | Verified distinction | Minimum recommended approval evidence |
|---|---|---|
| OpenAI API | API data is not used for training unless opted in; default abuse logs may retain content for up to 30 days. ZDR needs approval and does not cover every feature.[1] | Executed terms/DPA, no sharing opt-in, verified project-level ZDR, exact model/endpoint/features and processing region |
| Anthropic API | Commercial API data is not used for training without an agreement otherwise; ZDR is organization-specific and has feature, model, flagged-content and legal exceptions.[20][3] | Executed terms/DPA, confirmed organization ZDR, eligible model and features, documented exceptions |
| Mistral API | Documentation separates training opt-out from ZDR; approved ZDR covers supported stateless calls, not stateful files, agents, conversations or observability traces.[21][2] | Explicit API training opt-out, confirmed approved ZDR, paid account, eligible non-Labs model/endpoints, observability disabled |

Mistral's inference marketing states that API data is not used for training, while its help documentation instructs API customers to configure a training opt-out. The conservative approach is to document the actual account configuration and obtain written contractual confirmation rather than infer protection from marketing or payment status.[22][21][23]

OpenAI's under-18 guidance specifically says not to process personal data of children under 13, or below the applicable age of digital consent, without first implementing API ZDR. A parent-facing role or API key does not itself demonstrate that ZDR is enabled.[24][1]

Recommended cloud gateway rules: direct approved provider connection, minimum data, no real identities in schemas/metadata, no unapproved stateful storage, and no failover outside the authorized provider set. If a contract, account, model, feature or region fails eligibility, reject the request rather than silently relaxing the policy.

Redaction should be defense-in-depth, not permission to export arbitrary learner text: sensitive details can remain in free-form content, and OWASP recommends minimizing access as well as sanitizing inputs.[25]

## Evidence before making claims

The following are proposed acceptance checks, not reported results:

- Stop or time out the local model with cloud keys present: no external inference request occurs.
- Supply public URLs, local forwarding proxies, redirects, alternate ports and changed DNS answers: unapproved destinations are refused.
- Attempt outbound traffic from the model, backend, speech worker and native subprocess using IPv4, IPv6 and DNS: policy enforcement is observed at the network boundary.
- Run representative chat, voice, quiz, OCR and practice paths while capturing traffic with sample data: every destination is explained and approved.
- Use two sample families and two school tenants: prompt injection and forged learner IDs cannot retrieve another tenant's data.
- Inspect support bundles, telemetry, crash logs and error reporting: no prompts, answers, recordings, keys or uploaded documents leave through observability.
- Exercise restart, upgrade, retry and provider outage paths: effective privacy policy persists and failover remains constrained.
- Inspect model storage and runtime configuration: no production training process, data upload job or unapproved cloud-model route exists.

Record the candidate SHA, platform, effective configuration, model/runtime versions, test commands and evidence artifacts. A successful application test alone is not proof of the whole trust boundary: Docker's network exceptions and OWASP's separation-of-privilege guidance support testing the network and authorization layers independently.[6][8][14]

## Rollout boundary

Recommended first delivery: a single private-mode policy applied consistently to ordinary homeschool and school operation, with constrained adapter selection, no external MCP, local multimodal paths and network enforcement. Preserve the existing offline installation's supported topology instead of simply switching every deployment to loopback-only.

Keep optional cloud drafting and future local-TTS improvements separately reviewable. This assessment adds no automatic RC blocker: any release decision should compare the measured behavior against the privacy promises actually made for that release. Unverified protections must be recorded as unverified, and external processing must never be labeled "data never leaves."

## What the code does today (2026-11-17, `main` plus PR #862)

Read against the code, not the matrix alone. Nothing below is changed by this document.

| Area | Today | Gap against the target above |
|---|---|---|
| Ordinary homeschool routing | `BEDE_ADAPTER_ORDER` with live failover across every configured provider (`services/adapters/router.py`) | No private mode. A configured cloud key is a fallback for a failed local model |
| School pilot | `EDUCATOR_PILOT_ENABLED` or `BEDE_COPPA_ENFORCE` allow only `local` (`core/coppa_provider_policy.py`), at loopback, `host.docker.internal` or any private-range address; isolated HTTP client with no proxy and no redirects | Any private-range host is accepted; no service identity, TLS pinning or forwarding check |
| Offline homeschool | `BEDE_OFFLINE_INSTALLATION`: loopback model only, Python-level egress block (`core/offline_boundary.py`) | No OS/container-level enforcement shipped with it |
| External MCP | Parent "Ask Bede" sandbox only, off unless both `MCP_EXTERNAL_*` settings are set; never in a lesson, the teacher chat or the demo (`services/mcp_client.py`) | Allowed in an ordinary homeschool parent workspace; the target disables it in private mode |
| Provider headers (PR #862) | `AI_PROVIDER_HEADERS` and per-server MCP `headers`, checked at boot (`core/request_headers.py`) | Neutral: headers change what a permitted request carries, never which provider or server is permitted. A future private mode must still be able to turn MCP off whatever headers are set |
| Speech | Transcription is local (faster-whisper) by default and OpenAI on the demo; Bede's voice is OpenAI TTS whenever `OPENAI_API_KEY` is set, otherwise the browser's voice. School mode refuses OpenAI transcription and TTS (`require_external_feature`) | Ordinary homeschool sends speech to OpenAI whenever a key is set; browser-voice `localService` selection is not built |
| Training | No training, fine-tuning or feedback-upload job exists in the codebase, which matches the owner's ruling that training happens only under the authorized team's supervision | Nothing asserts that it stays that way |
