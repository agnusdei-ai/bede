# Risk Assessment Policy

**DRAFT for owner approval. Not in effect.** Sections marked
**[OWNER DECISION]** must be decided before approval.

Owner: the designated individual in `docs/INFORMATION_SECURITY_POLICY.md` §2.

## 1. When

A full risk assessment runs at least **[OWNER DECISION: once a year]**, and
again when any of these happens:

- a new in-scope system or vendor;
- a change to what data is collected, or from whom;
- a confirmed security incident;
- a material finding from a test or an assessment.

## 2. How

1. Start from the existing threat model (`docs/THREAT_MODEL.md`, adversary
   classes A1 to A9), the open gaps in `docs/SECURITY.md`, and the AI risk
   mappings (`docs/OWASP_LLM_TOP10.md`, `docs/NIST_AI_RMF.md`).
2. For each risk, record: what could happen, to which system and data, how
   likely it is and how much harm it would do (low, medium or high, with a
   sentence on why), the controls that reduce it, and the residual risk.
3. Decide for each risk: reduce it, transfer it, avoid it, or accept it.
   An accepted risk gets an exception record
   (`docs/audit-readiness/README.md` §3), with an owner and a review date.
4. Include risks specific to AI and to children: incorrect teaching
   content, unsafe suggestions, prompt injection, data reaching a provider it
   should not, and the safeguarding paths. The harm-to-control map for
   AIUC-1 is built from this step.
5. Include fraud and misuse risks: licence abuse, demo cost abuse, and
   impersonation of a parent or school.

## 3. Record

Keep each assessment in `docs/audit-readiness/risk/<date>.md` **[OWNER
DECISION: or a private location, if the content is sensitive]**. A risk
register in a public repository should name controls and decisions, not
detailed attack paths that are not yet closed.

## 4. Evidence an assessor will sample

- The dated assessment, with the owner's sign-off.
- Exception records it produced.
- Evidence that the decided remediation happened.
