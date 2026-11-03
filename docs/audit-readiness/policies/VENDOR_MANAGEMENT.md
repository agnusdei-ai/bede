# Vendor Management Policy

**DRAFT for owner approval. Not in effect.** Sections marked
**[OWNER DECISION]** must be decided before approval.

Owner: the designated individual in `docs/INFORMATION_SECURITY_POLICY.md` §2.
Review: at least annually, and before any new vendor receives data.

## 1. Vendors in scope

The vendors that receive data from the operator's own systems, from
`docs/INFORMATION_SECURITY_POLICY.md` §5 and `docs/VENDOR_DATA_FLOW.md`:
OpenAI, Mistral, Anthropic (when configured as the backup), Resend, Render,
Cloudflare and GitHub. Add Stripe if the license server's checkout is used
during the period. Wikimedia receives only a public article title from the
child's browser and holds no account relationship; list it, but it needs no
assessment.

A family's self-hosted installation chooses its own AI provider. That choice
is the family's, and is out of scope here.

## 2. Assessment before use

Before a vendor receives data, and then every **[OWNER DECISION: year]**,
record in `docs/audit-readiness/vendors/<vendor>.md`:

| Item | What to record |
|---|---|
| Data sent | Exactly what the vendor receives, from `docs/VENDOR_DATA_FLOW.md` |
| Assurance | Its SOC 2 report (or equivalent) and the period it covers, the date it was read, and any exceptions it lists that matter here |
| Contract | The data processing terms in force and the date accepted |
| Training use | Whether the vendor may train on the data, and the account setting or contract term that controls it |
| Retention | How long the vendor keeps the data, and any zero-retention option in use |
| Subprocessors | Where the list is published, and the date checked |
| Children's data | Whether the vendor's terms allow data about children, checked with counsel |
| Decision | Approved, approved with conditions, or not approved; who decided and when |

A vendor whose terms cannot be confirmed is not approved, and the feature
that would use it stays off.

## 3. Changes

Changing which vendor is primary or backup for AI changes who processes a
child's conversation. It needs the owner's review first, and the privacy
notices and `docs/RETENTION_POLICY.md` must be updated in the same change
(`docs/INFORMATION_SECURITY_POLICY.md` §5 already requires this, and
`tests/test_coppa_compliance.py` checks the vendor names stay consistent).

## 4. Evidence an assessor will sample

- Each vendor's record and the reports and terms it cites.
- The dates of each review.
- The record of any vendor change and its approval.
