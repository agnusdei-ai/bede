# Access Control Policy

**DRAFT for owner approval. Not in effect.** Sections marked
**[OWNER DECISION]** must be decided before approval.

Owner: the designated individual in `docs/INFORMATION_SECURITY_POLICY.md` §2.
Review: at least annually, and before anyone new is given access.

This policy covers access to the company's own systems. Who may do what
inside the Bede application (parent, child, educator, demo roles) is a
separate document: `docs/AUTHORIZATION_POLICY.md`.

## 1. Systems covered

| System | What access allows |
|---|---|
| GitHub (`agnusdei-ai` organization) | Changing code, CI and release workflows; repository settings and secrets |
| Render | The demo API, its database and its environment variables |
| Cloudflare | The site, the license server, D1, DNS and Worker secrets |
| AI provider and Resend accounts | API keys, usage, and data-retention settings |
| Email inboxes that receive feedback and sales enquiries | Messages from families and schools |
| Signing keys (licence signing key, installer signing identities) | Issuing licences and signed installers |

## 2. Who has access

Today one individual holds production access to every system above
(`docs/INFORMATION_SECURITY_POLICY.md` §6). The coding agent works through a
GitHub integration with repository-scoped permissions and holds no provider
dashboard credentials.

Keep a list in **[OWNER DECISION: location]** of every person and automated
identity with access to each system, the level of access, and why it is
needed.

## 3. Rules

1. Access is given only for a stated need, at the lowest level that meets it.
2. Every human account on the systems in §1 uses multi-factor
   authentication, and a hardware security key where the system supports it.
   **[OWNER DECISION: confirm this is already true for each system]**
3. Shared accounts are not used. Automated identities (CI tokens, deploy
   keys) are scoped to one purpose and listed in §2's record.
4. Secrets live in the provider's secret store (GitHub Actions secrets,
   `wrangler secret`, Render environment variables), never in the repository.
   The repository's own guards check for committed secrets.
5. Access is removed on the day it is no longer needed.

## 4. Reviews

Every **[OWNER DECISION: quarter]**, review §2's record against each
system's actual member list, and record the date, what was checked, and any
change made. With one person this is still worth doing: it catches forgotten
tokens, old deploy keys and integrations that no longer need access.

## 5. Evidence an assessor will sample

- The access record and each review.
- Screenshots or exports of member lists and MFA status from each system.
- The record of any access removed, with its date.
