# Valor prepilot — administrator handoff

**Purpose:** Let nontechnical Valor school leaders experience Bede's proposed teacher-directed workflow with no sign-in, installation, student information or vendor credentials. **Not** a school deployment, certified assessment tool, or Pilot GO.

## Open and experience

1. In the operator bundle, double-click **Open-Bede-Prepilot.html**. No Docker or network needed.
2. In **Official result**, transcribe an *illustrative* DIBELS 8, NWEA MAP or STAAR report: campus, learner, grade, date, source and form/report identifier, benchmark/progress purpose, period, Valor quarter, measure, scored or unscored status, and optional official composite copied verbatim.
3. In **Teacher observation**, enter classroom evidence separate from the standardized result.
4. In **Data Day**, examine both records and approve, edit or reject an illustrative instructional next step. No instruction is delivered.
5. **Review record** presents a chronological simulated action trail and local export for discussion.

**Guardrails:** Proprietary assessment passages, items, prompts and scoring tables are never recreated. Skipped, not administered, invalid and other non-scored statuses remain nonnumeric (\`raw_score: null\`), never zero. No composite is inferred. The sample teaching prompt is static and explicitly not inference. A correction appends a linked replacement record; the previous simulated record is retained in the exported trail.

## What Valor's 2025–26 District Improvement Plan actually establishes

- Valor describes NWEA MAP being administered three times per school year, alongside continuous classroom formative assessment.
- Its evidence-of-impact table references performance or growth in **NWEA MAP, DIBELS and/or STAAR**, using BOY/MOY/EOY monitoring and classroom observation/lesson plans.
- Valor describes classical curriculum, Socratic questioning, presentation, coaching, and hands-on instruction.

Source: **Valor Education, District Improvement Plan 2025–2026**, board approval November 24, 2025, especially pp. 11, 19–21 (PDF page numbers displayed in the document may differ from physical PDF indexes):
https://static1.squarespace.com/static/62bb35f256ba253716ea0383/t/6937044063831b22abcbdeed/1765213248269/Valor+Education+DIP+2025-26.pdf

The DIP **does not** identify Valor's currently approved DIBELS edition, individual form IDs, scoring platform, assessment-system API, consent regime, or exact test windows. Those remain the assessment lead's decisions, not assumptions made by Bede. The preview is **not** a representation that any integration or licensed assessment administration is authorized.

## Prepilot versus qualified pilot

| Experience | Assessment data | Credentials | Real services | Evidence |
| --- | --- | --- | --- | --- |
| **Prepilot walkthrough** | Fixed fictional learner, locally entered illustrations only | None | None; file opened offline | Exported JSON and browser-tab simulation trail. Not cryptographically verified |
| **Installed G3 candidate** | Synthetic only | Real authorized WebAuthn/passkey + operator configuration | Local Docker application and database | Real G1/G2 lifecycle, restart/revocation/deletion tests and redacted evidence |
| **Future live Valor pilot** | Not authorized in this iteration | Institution-owned identities | Requires separate GO | Separate acceptance and data/privacy authorization |

The authenticated pilot is **teacher-only**: assessment → Data Day → recommendation → teacher approve/edit/reject → recorded plan → teacher personally instructs → observation/checkpoint. **delivery_state = NOT_REQUESTED**. The prepilot does not infer or certify its operational security.

## Installation and diagnosis

For the installed candidate, use **Install-Bede.command**. The shell launcher produces \`bede-support/setup-<UTC>-<pid>.log\` locally on every attempt, including failures during architecture selection, Docker readiness, image import, wizard, configuration, container startup or HTTPS health. Each report contains a status and a short fixed stage name, without environment variables, credentials, student details or raw container logs. It is the operator's first support artifact. Run **Verify-Bede.command** after successful setup to gather additional private smoke-test evidence.

**Do not send** \`.env\`, passkeys, screenshots containing student information, API keys or database exports. Never claim successful physical Mac verification unless it was observed.

## Prepilot reviewer feedback

Ask the reviewer just three questions: **Could you open it without help? Could you tell what the teacher was approving? Could you download the meeting record?** Note what blocked those actions. No long engineering questionnaire is required.

