# Parental verification: narrowest suitable method (proposal for review)

Status: proposal for counsel and owner review. Nothing here is approved; every
method stays unavailable (`available=False`) until reviewed. Attestation alone
is recorded as attestation, never as verified consent.

## Principle

Choose the narrowest method that fits what the installation actually does with a
child's data. No general identity platform; no identity documents collected for
convenience.

## Decision input: the actual data flows

| Deployment | Child data leaves the household? | Candidate method |
| --- | --- | --- |
| Local-only AI (local model, no third-party provider) | No | Email-plus: confirmation email to the parent, followed by a delayed confirmation step |
| Cloud AI provider configured (child text/voice sent to a third party) | Yes (disclosure) | A method the FTC lists for disclosure cases, e.g. a monetary transaction with notice to the account holder, or knowledge-based verification |

The installer already knows which applies (provider configuration), so the
method follows the configuration instead of asking the parent to choose.

## Proposed default

1. Local-only: email-plus. The parent enters a contact address at install; a
   confirmation link is sent; a second confirmation (after a delay) completes
   verification. No documents, no new vendor.
2. Disclosure to a provider: require a method from the FTC's recognized list.
   Smallest implementation: the existing license-server purchase transaction
   (already a monetary transaction with the parent) acting as the verifying
   event, with the receipt recording the transaction reference only.

## Not proposed

Government ID upload, face match, third-party identity platforms, data brokers.

## Open for counsel

- Whether email-plus is sufficient for a custodian-controlled, local-only install.
- Whether the license purchase can serve as the disclosure-case method.
- Retention of the verification evidence (proposed: reference id and timestamp
  only, in the receipt).

## Consequence until approved

Family receipts remain `pending_verification` and child-data processing stays
off. Schools are unaffected (their path is the signed campus key plus documented
delegation and notice acceptance).
