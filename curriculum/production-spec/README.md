# Proprietary curriculum production contract

Status: **specification and sample fixtures only**, November 12, 2026.
No lesson, source, grade, pilot, or instruction is approved by this package.
Bede-owned content and tooling remain subject to the repository's proprietary
LICENSE. Existing third-party notices and the separately licensed
`agent-governance/` component are unchanged. No blanket open license is granted.

**PR preparation, November 13, 2026:** restored from the verified original source
handoff onto main `5620bfaab4f3a2f0bfbd96180b8330f1b2d68816`, after the Grade 8
baseline merge. Original no-push and queued-task statements in this package
describe the historical specification delivery. The owner now authorizes scoped
curriculum PR publication and deployment triggered by that operation. This does
not approve a curriculum lesson, issue institutional reviewer authority, enable
the runtime flag or lift Pilot HOLD. See [PR verification](PR-VERIFICATION.md)
for current checks and public-repository screening.

## Architecture decision

Extend the existing curriculum domain, not a second delivery or approval system.
Production manifests add pedagogy, exact source permissions, assessment and output
contracts around existing `SourceRecord`, `Lesson`, `ContentChunk`, `LessonVariant`
and versioned campus staging. The development ledger tracks work and evidence;
it **cannot authorize delivery**. Only the existing authenticated independent
review workflow can promote a campus lesson. Agent review is production academic
evidence, never an impersonated human `ReviewRecord`.

Bede is parent-directed and Bede-orchestrated, serving families, co-ops, and
qualified charters. Adults retain placement, safety, and consequential decisions.
Combine explicit teaching and worked examples with classical seminar/studio,
substantial reading, revision, and practical STEM/AI. Approved supports count as
competent independence; record prompting rather than treating access as cheating.
Do not assert measured efficacy, time savings, credit, charter qualification, or
complete-year availability from a schema, catalog, sample check, or agent review.

## Executable contract

Python 3.11+ standard library only. No installation, database, provider, network,
learner records, secrets, environment changes, or application startup is needed.
Run from this directory:

```sh
timeout 35s python3 -B verify.py
python3 -B contract.py check
python3 -B contract.py schema
python3 -B contract.py export
python3 -B example.py
```

`verify.py` enforces a 30-second alarm, 256 MiB address space and 10 MiB
per-file output limit before loading the tests. It applies limits inside Python,
after the environment's wrapped launcher starts. On a host without the Linux
`resource` interface, it fails rather than claiming limits were enforced.

`schema.py` is the structured specification: it emits JSON Schema 2020-12 with
closed objects, required fields, and explicit enums. Its small, fail-closed
validator implements only the keywords used here and rejects unknown keywords.
`contract.py` adds graph, rights-use, content hash, assessment coverage, ledger,
and upstream model checks. These checks establish structure and selected
invariants, **not educational validity or authentic approval**. See tests for
negative cases. `example.py` computes exact-version child references and emits
the full JSON bundle. An optional JSON input path to `check`/`export` validates a
stored bundle with assets confined to that input's directory. The fixture's
bytes are original sample pairs, not a teaching
sequence, licensed corpus, or learner evidence. Export writes canonical JSON to
stdout; redirect only to a dedicated ignored generated-output directory.

Read [INVENTORY.md](INVENTORY.md) for inspected evidence and pending inputs,
[PRODUCTION.md](PRODUCTION.md) for implementation and ledger semantics, and
[GATES.md](GATES.md) for completion and authorization rules.

## Integration handoff

The queued development-only factory owns scheduling, durable storage, authenticated
receipt resolution, process limits, cancellation, and crash recovery. It must
consume this contract without registering a route, changing startup/DDL, enabling
the curriculum flag, issuing grants, or automatically promoting content.
The three-lesson Grade 8 slice follows that factory and supplies actual
independent evidence. The Grade 8 baseline is concurrent context, **not a circular
dependency** preventing generic contracts. Full-year Grade 8 and subsequent
Grades 9–12 consume these contracts; they are not prerequisites for this spec.

No remote writes, branch creation, PR, merge, deployment, production activation,
paid inference, training, student data, or live pilot is authorized. The local
specification commit is not a release. Preserve all prior milestone decisions.
