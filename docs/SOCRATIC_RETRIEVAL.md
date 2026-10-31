# Socratic retrieval and adult planning

## Learning boundary

Bede's tutor and adult workspace instructions preserve active learning tasks:
guiding questions and conceptual breadcrumbs, without solved equations, finished
thesis statements, or completed student work. Administrative questions can still
receive direct answers. These are model instructions, not a mathematical guarantee
that a generative model will never reveal an answer. Safeguarding takes precedence.

Authenticated parents use the existing sandbox. Passkey-authenticated school
educators use `/lesson-planner`, backed by `/sandbox/educator-chat`. The server—not
prompt text or a client role flag—selects adult formatting:

- **Pedagogical Intent:** one sentence naming the concept.
- **Scaffolding Prompts:** three questions progressing from observation to
  explanation and transfer.
- **Differentiation Vector:** Remedial, On-Level, and Advanced/Extension options.

The school endpoint has no external MCP tools, roster access, or learner records.
Do not paste personal student details. Learner-facing tutoring remains a separate
experience; an educator operating a child's session does not change its format.
Headings follow the session language, including general Spanish.

## Reviewed, local curriculum retrieval

`services.curriculum.pedagogical_retrieval.retrieve_for_learning` composes the
existing offline index and citation ranker. It requires an already-authorized
campus/educator scope, objective, K–8 grade, and separately human-reviewed metadata.
It does not authenticate callers or create its own standards mappings.

Grade and objective filtering happen before tokenization and top-k selection.
Existing campus, private-owner, rights, approval, and source-edition checks remain.
Unknown grade review is excluded. Standards are exact catalog identifiers, not
model-invented TEKS or Common Core claims.

With a pedagogical profile, the score is 60% existing relevance/review score,
20% primary-source status, 15% exact reviewed standards match, and 5% modularity.
After retaining the strongest result, selection favors distinct reviewed
perspectives before repeating one. All results must pass the same eligibility
filters; diversity never authorizes an otherwise disallowed source.
Without a profile, existing citation scoring remains unchanged.

**Integration status:** the curriculum engine remains feature-gated and disabled
by default. This service primitive is not wired into live tutoring or exposed as
an unauthenticated search endpoint. An authorized integration must load current
review records, check live grants/revocations, and supply an approved corpus.
The new review metadata is supplied by the caller; this change does not add a
review-authoring UI or persist new metadata.

The index uses BM25 and deterministic feature-hashed local lexical vectors,
not pretrained neural embeddings. No model weights are fetched or implied.
It has no query logging, model call, network access, or federated web fallback.
Neural semantic retrieval would require a separately provisioned, validated local
embedding model; this change does not install or download one.

## Offline school and family installations only

Opt in with `BEDE_OFFLINE_INSTALLATION=true` and a preprovisioned local model at
a loopback `LOCAL_LLM_BASE_URL`, for example `http://127.0.0.1:8000/v1`.
Keep the flag false for the hosted demonstration; its provider setup is unchanged.

In offline mode:

- Missing or non-loopback model configuration prevents startup.
- Cloud model adapters are denied, including manual provider switches and fallback.
- The API installs a Python audit hook before importing service clients. It denies
  non-loopback TCP/UDP destinations and external DNS lookups without logging query
  text or destination details.
- Unix sockets and loopback services remain usable. A remote PostgreSQL server,
  email relay, web search, cloud voice service, telemetry endpoint, or model
  download will be blocked. Provision all required models and services locally.
- Restart the process to change modes. Do not enable this in a running hosted
  installation as a substitute for an offline deployment.

**Deployment qualification is still required.** A Python audit hook is defense in
depth, not an operating-system sandbox or a certified air gap. Native extensions,
subprocesses, a separate local model server, and the browser must be isolated by
the installation's firewall/network policy too. A loopback proxy must never
forward to a cloud service. Preinstall weights, disable automatic downloads and
external telemetry, remove cloud credentials, and test the whole installation
with external egress denied before admitting student data. Do not advertise an
air gap, FERPA/COPPA certification, or guaranteed answer prevention based on these
code changes alone.
