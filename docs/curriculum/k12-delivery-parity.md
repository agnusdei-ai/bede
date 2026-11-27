# K–12 curriculum delivery parity

## Required product behavior

The hosted demo, installed API, and Apple delivery must use the same accepted
curriculum sources, grade selection, and tutoring behavior. Demo session limits
do not define a separate curriculum tier. Content availability, review, source
rights, and adult selection are independent of delivery method.

## Current integration inventory

This is a runtime inventory, not a claim that curriculum authoring is complete.

| Grades | Current default source | Registered accepted full year |
| --- | --- | --- |
| K–1 | Catalog year 1, curated books and subject guidance | None registered |
| 2–7 | Corresponding catalog year, curated books and subject guidance | None registered |
| 8 | Catalog year 8, or the adult-selected accepted year | `bede-grade8-2026-accepted` |
| 9–12 | Exact-grade Socratic practice guidance | None registered |

Authored upper-school material also exists outside the runtime data directory.
Its existence is not evidence of a published, complete, accepted runtime release.
Continue the existing Grades 9–12 curriculum completion work; do not start a
duplicate authoring stream or expose adult keys while connecting student content.

## Shared contract

`GET /catalog/curriculum-availability` returns one ordered K–12 inventory,
independent of authentication role or delivery type. Both setup clients use it.
The response contains only source metadata, not learner records, private
assessments, or lesson answers:

- `contract_version`: response schema version, currently 1.
- `grades`: the same valid grade order used by session configuration.
- `default_route`: `catalog_guided` or `grade_specific_practice`.
- `catalog_year` and `catalog_sha256`: the actual catalog source, or null.
- `accepted_full_year`: accepted release identifier, source digest, reviewed
  record count, and effective operator enable setting, or null.

The same catalog-year resolver now supplies the tutor prompt route. K/0 aliases
remain compatible; grades 9–12 are never mapped to a lower-grade catalog. Existing
upper-school prompt guidance applies to all sessions, not a special demo course.
K–8-only diagnostic instruments remain K–8-only; curriculum parity does not
validate them for high-school learners.

Clients refresh availability on focus and once per minute. Unknown schema
versions, missing grades, failed requests, and malformed enable flags are not
shown as successful activation. Metadata does not choose or advance a course:
the existing adult-authoritative Grade 8 selection/save/reload contract remains
unchanged.

## Packaging and Apple findings

The operator build uses the shared `homeschool-api` Docker build context.
That Dockerfile copies the application, including its curriculum data.
The operator bundle references immutable API image tags rather than maintaining
another curriculum repository. This is source/build-path evidence, not a tested
customer installation.

An existing Capacitor iOS app and Swift package are present. Its configuration
explicitly says the native HTTPS API integration still needs separate validation;
the web `/api` path cannot be assumed to work under `capacitor://localhost`.
This change does not qualify an App Store build or introduce an unapproved
public endpoint for private installed learner data.

## Remaining completion criteria

1. Merge and deploy the separate Grade 8 activation correction after its required
   review; verify the live API reports the expected effective setting.
2. Complete and review missing full-year source instruction, with separate
   student/adult boundaries, using the existing factory and ordered grade work.
   Catalog metadata and practice prompts must not be relabeled as those lessons.
3. Connect each accepted grade release to shared selection and actual tutor
   retrieval; extend this inventory as real adapters become available. Verify
   beginning, middle, end-of-year, and alternate-path lessons in both clients.
4. Compare source digests and saved selections in deployed and installed
   runtimes. Qualify installer artifacts and the native HTTPS integration
   separately, preserving local-first privacy.

Until those checks pass, report the individual completed increments rather than
claiming complete K–12 publication or parity across released installations.
