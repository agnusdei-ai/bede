# K–2 Early Learning Pilot: UX Design Specification Checklist

**Status in this repository: the owner's design baseline for K-2 work,
adopted 2026-11-16.** Part 2 is the checklist verbatim, as the owner supplied
it. Part 1 records how it applies to Bede: the owner's rulings
on the places it conflicted with Bede as built (`docs/DECISIONS.md`
entry 42), and where Bede stands today against each section. Every check is
still open. Nothing here is an audit or a compliance certification, and the
checklist says the same of itself.

## Part 1. How this applies to Bede

### The owner's rulings (2026-11-16, decision entry 42)

The checklist was written for a generic tablet pilot. Four of its assumptions
conflicted with Bede as built, and the owner ruled on each:

| Question | Ruling | What it changes |
| --- | --- | --- |
| Deployment | **Both**: the school campus pilot (shared classroom devices, teacher-managed roster) and home families (a family's own tablets) | Two consent routes, each verified on its own: school authorization (PRIV-04) and verifiable parental consent (PRIV-03). The shared-device checks (INT-08, the "Shared device" acceptance test) apply to both: siblings share a family tablet too. |
| Generative chat and microphone | **In scope**: the pilot includes Bede's tutoring chat, not only the K-2 practice rounds | The checklist's out-of-scope list no longer holds for generative chat, the microphone, or a child's voice. As the checklist says, adding them reopens privacy, safety and UX review, so the chat, voice capture and transcription each need that review before enrollment. The K-2 practice rounds themselves stay deterministic: built by code, with nothing from a round sent to any AI provider (`K2_PRACTICE.md` §6). |
| Palette | **Brand tokens, held to the checklist's floors** | Each colour role below maps onto the existing agnusdei.ai ramps (`VISUAL_IDENTITY.md`). No new palette; `palette.test.ts` stays the guard. |
| Text at 200% | **A 200% step on the text-size control, app-wide** | The control currently stops at 175%. TYPE-04 is verified on every screen at 200%, not only on K-2 screens. The public demo's copy of the control is changed only with the owner's separate sign-off (`demo/` carve-out). |

### The palette, mapped onto the brand

The checklist's ratios were recomputed and match its table exactly. The same
roles on the brand tokens, measured the same way (opaque flat sRGB pairs):

| Role | Background | Foreground | Contrast |
| --- | --- | --- | --- |
| Canvas / primary text | vellum `#faf6ec` | ink `#1c2438` | 14.32:1 |
| Primary action | fern `#47613f` | white | 6.89:1 |
| Success panel or action | fern-deep `#33482d` | white | 9.97:1 |
| Encouragement / highlight | gilt-light `#e0b84a` | ink `#1c2438` | 8.19:1 |
| Retry / gentle notice text | white | madder `#8c3b2e` | 7.55:1 |

Every pair clears the checklist's 4.5:1 text floor (COL-01). The pale
instruction and retry panels have no measured brand pair yet; they are
measured on the real ground in the build that introduces them, as
`VISUAL_IDENTITY.md` requires, and keep a dark border where their edge carries
meaning (COL-02). Retry is never red-for-wrong alone: it pairs a word and an
icon with the colour (COL-03), and Bede never says "wrong" (`K2_PRACTICE.md`
§3).

### Where Bede stands today

Read against the code on `main` at the time of writing. "Meets" means the
behaviour exists, not that the check has passed: every check still needs
evidence from the actual build.

| Area | Where Bede stands | Gap |
| --- | --- | --- |
| Touch targets (INT-01) | Phonics practice (`K2PhonicsPractice.tsx`) and the routine frame's close button are 56 px, the main action 64 px, 8 px apart, in rem so they grow with text size; checked by class contract, not yet measured in a browser. Map practice's own controls are still 44 px. | Raise map practice's controls; measure rendered hit areas on the actual build. |
| Text resize (TYPE-04) | The text-size control stops at 175%. | The 200% step (ruling above), then a check on every screen. |
| Activity length | A round is Watch, then two Together items, then three Your turn items, about five minutes (`K2_PRACTICE.md` §1). | Kindergarten starts at about three minutes: fewer items per step for K. |
| Answer choices | Map practice draws its choices per task. | Start kindergarten at 2 to 3 choices, grades 1 and 2 at 3 to 4. |
| Font (TYPE-01) | No "dyslexia font", by test (`readingPresentation.test.ts`). | Curriculum approval of instructional `a`, `g`, numerals and handwriting models (decision 40(c)). |
| Motion (ENG-05) | Every animation honours `prefers-reduced-motion` (`K2_PRACTICE.md` §7). | Celebrations at or under 2 seconds, dismissible; a Quiet mode for adults (ART-07). |
| Pressure (ENG-04, ENG-06) | No timer, speed, score, streak or leaderboard is shown to a child; the K-3 break suggestions are optional and dismissible. | Evidence from the actual build. The mandatory hourly break is a screen-time rule, not a suggestion, and stays. |
| Correction (ENG-02) | A miss shows the move again; after two tries the answer is shown (`K2_PRACTICE.md` §3). | Hint wording reviewed by the curriculum lead. |
| Narration (TYPE-06, TYPE-07) | Every line Bede speaks in a round is written per locale and spoken. | Confirm narration never reads out an answer when decoding is the skill. |
| Languages (TYPE-08) | English and Spanish, same keys in both locale files. | Test text expansion at 200%. |
| Consent (PRIV-03, PRIV-04) | A consent ledger gates household collection (`docs/PARENTAL_CONSENT.md`); the campus pilot has a school-authorization record (`core/school_authorization.py`). | Both routes verified separately (ruling above); legal review of each. |
| Shared devices (INT-08) | Campus learners are authorized per learner and grant (G1); a household shares one child PIN. | Prove learner B cannot reach learner A's history on a shared tablet, by URL, back navigation or roster name, in both deployments. |
| Retention (SEC-04) | `docs/RETENTION_POLICY.md` sets windows per category. | A justified window for every class the pilot adds; no "TBD". |
| Concurrency | The capacity run (`docs/CAPACITY.md`) fails at 10 concurrent children on the default database pool. | Fix before a classroom of ten uses it at once. |
| Apple devices | Release qualification runs WebKit 26.6 (`docs/release/WEBKIT_RELOAD_CRASH.md`). | The physical iPad and Safari sign-off is still required. |

---

## Part 2. The checklist (as supplied by the owner)

This checklist defines a proposed release baseline for a kindergarten-through-second-grade learning experience. It covers visual design, accessible interaction, child privacy, data security, and engagement that supports learning rather than prolonged use.

**Working assumptions:** A U.S., child-directed, tablet-first web pilot used on shared classroom devices, with teacher-managed enrollment. Home use is optional and must use an approved consent route before collecting children's personal information.

**Document status:** Proposed specification, not an audit or compliance certification. No implementation has been inspected; all checks remain open.

### Release rules and scope

- **P0, must pass:** Required before children use the pilot; a failed check blocks release of the affected flow.
- **P1, should pass:** May be deferred only with a named owner, mitigation, and due date.
- **P2, later:** Deliberately outside the initial release.
- **Evidence:** For every check, record `Status | Owner | Build/device | Evidence | Issue | Retest date`; use Not tested, Pass, Fail, or justified Not applicable.
- **Requirement basis:** Numerical UX targets below are proposed product decisions, not universal developmental standards. Explicitly cited WCAG and COPPA provisions are external requirements or guidance.

The accessibility target is WCAG 2.2 AA for the complete web experience, not merely the selected criteria highlighted here; a full conformance review is still required ([W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)). The privacy section supports implementation and legal review, but completing it does not establish COPPA compliance for a particular product.

#### Outcomes and non-goals

- **Independent use:** Children can start, understand, attempt, get help, and stop without an adult operating the interface for them.
- **Learning access:** Reading skill, motor precision, color perception, or audio availability should not unnecessarily block the intended learning objective.
- **Safe participation:** Only approved data is collected, adult controls are protected, and shared devices do not expose another learner's information.
- **Healthy engagement:** The product rewards effort and useful strategies, permits breaks, and offers clear stopping points.
- **Out of scope:** Advertising, purchases, public profiles, chat, social sharing, leaderboards, generative chat, child photo/voice uploads, and camera/microphone permissions. Adding any of these reopens privacy, safety, and UX review.

#### Core user stories

- **Kindergarten learner:** "I can hear and see what to do, then try it without reading a long instruction."
- **First-grade learner:** "I can ask for a hint and retry without losing my work."
- **Second-grade learner:** "I can choose an appropriate challenge without the interface treating me like a younger child."
- **Learner using assistive technology:** "I can understand and operate the activity through an equivalent accessible path."
- **Teacher or caregiver:** "I can help a child, manage access, and review progress without exposing other children's data."

### Grade-level starting profiles

Treat these as starting configurations to test, not fixed assumptions about every child. Reading, language, motor, sensory, and learning needs should override grade defaults.

| Design dimension | Kindergarten | First grade | Second grade |
|---|---|---|---|
| Instructions | One action at a time; illustration and replayable narration | One short sentence; optional worked example | One or two short sentences; steps disclosed progressively |
| Answer choices | Start with 2–3 | Start with 3–4 | Start with 3–4; add complexity through content, not clutter |
| Reading support | Narration readily available; no reading-only navigation | Text and narration together | Text-first option; narration still available |
| Challenge | Demonstration, then guided attempt | Attempt, hint, retry | Attempt, strategy hint, brief explanation |
| Starting activity length | About 3 minutes | About 3–5 minutes | About 5–7 minutes |
| Completion | Concrete visual outcome | Small progress sequence | Clear skill-based progress |

These durations are pilot design hypotheses, not recommended total screen-time limits. Children may stop at any point, and teachers may shorten activities.

### Artistic UI elements

**Primary owners:** Product designer, illustrator, curriculum lead. Review artwork in context on the smallest supported device, not only in a design canvas.

- [ ] **ART-01 · P0 · Clear hierarchy:** Each activity screen has one learning task and one visually dominant primary action. Decorative characters, scenery, and rewards never overlap instructions, answer choices, or navigation.
- [ ] **ART-02 · P0 · Consistent visual grammar:** Interactive objects have consistent shape, border, and state cues. Decorative objects do not look tappable; every actionable icon has a short visible label or an equivalent child-tested cue with narration.
- [ ] **ART-03 · P0 · Curriculum accuracy:** A curriculum reviewer approves every instructional illustration, including quantities, letterforms, number lines, and spatial relationships. Decorative objects cannot be mistaken for items a child should count.
- [ ] **ART-04 · P0 · Respectful representation:** Audit people, names, voices, families, abilities, and settings for stereotyping or exclusion. No essential instruction depends on unfamiliar cultural knowledge unless that knowledge is explicitly taught.
- [ ] **ART-05 · P0 · Complete asset states:** Deliver default, selected, pressed, focus, unavailable, success, retry, loading, and error states for applicable components. Meaningful images have appropriate text alternatives; decorative images are omitted from the accessibility tree, consistent with WCAG's non-text-content requirements ([W3C, SC 1.1.1](https://www.w3.org/TR/WCAG22/#non-text-content)).
- [ ] **ART-06 · P1 · Restrained illustration system:** Use a documented family of corner radii, strokes, shadows, and character expressions. Kindergarten and second-grade screens share the system but can use different themes selected without changing task difficulty.
- [ ] **ART-07 · P1 · Quiet mode:** An adult-accessible setting removes decorative animation and background music without removing teaching content or feedback.

### Child-friendly color palette

Use calm surfaces with selective saturated accents. The palette below is a proposed starting point, not a claim that particular colors improve learning or work equally well for every child.

| Token / role | Background | Foreground | Calculated contrast |
|---|---|---|---|
| Canvas / primary text | Warm cream `#FFF9F0` | Ink `#24324B` | 12.29:1 |
| Primary action | Blue `#2457A6` | White `#FFFFFF` | 7.03:1 |
| Success panel or action | Green `#286447` | White `#FFFFFF` | 6.99:1 |
| Encouragement / highlight | Gold `#F6C85F` | Ink `#24324B` | 8.17:1 |
| Instruction panel | Pale blue `#DDEBF8` | Ink `#24324B` | 10.60:1 |
| Retry / gentle notice | Peach `#F7DFD8` | Ink `#24324B` | 10.11:1 |

Ratios are calculated for opaque, flat sRGB pairs and rounded to two decimals. They do not validate gradients, disabled states, image overlays, or component boundaries; pale panels need an additional dark border or other sufficient cue when their boundary conveys meaning.

- [ ] **COL-01 · P0 · Text contrast:** Use at least 4.5:1 for all instructional and control text as the pilot standard, even when large text would qualify for WCAG's 3:1 exception ([W3C, SC 1.4.3](https://www.w3.org/TR/WCAG22/#contrast-minimum)).
- [ ] **COL-02 · P0 · Non-text contrast:** Essential control/state cues and instructional graphic details achieve at least 3:1 against adjacent colors, subject to the criterion's exceptions ([W3C, SC 1.4.11](https://www.w3.org/TR/WCAG22/#non-text-contrast)).
- [ ] **COL-03 · P0 · More than color:** Pair success, retry, selection, and progress colors with words, icons, shapes, or patterns; color is never the only way information is conveyed ([W3C, SC 1.4.1](https://www.w3.org/TR/WCAG22/#use-of-color)).
- [ ] **COL-04 · P0 · State audit:** Test every foreground/background pairing in default, focus, pressed, selected, error, and loading states. Avoid white text on the gold, pale blue, or peach tokens.
- [ ] **COL-05 · P1 · Classroom validation:** Review the palette in grayscale, with color-vision simulations, and on supported devices under classroom lighting. Adjust based on observed confusion or discomfort, not color stereotypes.

### Typography, language, and audio

**Proposed type tokens:** Instruction text 24–28 CSS px; answer/control labels 22–24 CSS px; headings 30–36 CSS px; adult-only supporting text at least 16 CSS px. Use a starting line height of 1.4–1.6, left alignment for English prose, and no essential child-facing fine print.

- [ ] **TYPE-01 · P0 · Legible letterforms:** Choose a readable typeface with distinguishable `I/l/1`, `O/0`, and `b/d/p/q`. The curriculum lead approves instructional `a`, `g`, numerals, and handwriting models; do not claim a font "treats dyslexia."
- [ ] **TYPE-02 · P0 · Plain instructions:** Use concrete verbs such as "Tap," "Match," and "Listen." Start with no more than 8 words per instruction for kindergarten and 12 for grades 1–2; exceptions require child testing.
- [ ] **TYPE-03 · P0 · Consistent labels:** Use the same words for the same actions throughout. Avoid idioms, all-caps sentences, decorative body fonts, and instructions that refer only to position or appearance.
- [ ] **TYPE-04 · P0 · Scaling and spacing:** No content or functionality is lost at 200% text resize or under the specified WCAG text-spacing overrides; those override values are not mandatory default styling ([W3C, SC 1.4.4 and 1.4.12](https://www.w3.org/TR/WCAG22/)).
- [ ] **TYPE-05 · P0 · Responsive reading:** Verify reflow at 320 CSS px width for applicable content, with exceptions only where a two-dimensional layout is essential ([W3C, SC 1.4.10](https://www.w3.org/TR/WCAG22/#reflow)).
- [ ] **TYPE-06 · P0 · Audio access:** Instructions have replayable narration and a persistent, clearly labeled audio control; speech does not overlap other speech. Provide equivalent visual/text directions and appropriate media alternatives, without assuming captions alone serve a non-reader.
- [ ] **TYPE-07 · P0 · Preserve the learning objective:** Narration may read navigation and instructions but must not automatically reveal an answer when decoding is the skill being assessed. For auditory-only objectives, provide an educator-approved accommodation and flag adapted results rather than claiming equivalent measurement.
- [ ] **TYPE-08 · P1 · Language support:** If multilingual learners are in the pilot, localize essential onboarding, help, and adult notices before enrollment. Test translated text expansion, pronunciation, and culturally appropriate examples.

### Touch targets, navigation, and recovery

For this web pilot, use **56 × 56 CSS px minimum hit areas**, **64 × 64 CSS px or larger for primary actions**, and **at least 8 CSS px between hit areas**. These are proposed child-oriented targets; WCAG 2.2 AA specifies 24 × 24 CSS px with exceptions, while its enhanced AAA criterion specifies 44 × 44 CSS px with exceptions ([W3C, SC 2.5.8 and 2.5.5](https://www.w3.org/TR/WCAG22/)).

If the pilot becomes a native application, define platform-specific logical-unit tokens and validate physical usability on devices. Do not equate CSS pixels with hardware pixels.

- [ ] **INT-01 · P0 · Large, unambiguous targets:** Measure rendered hit areas, not just icon dimensions. Hit areas never overlap; layouts preserve target sizes at supported orientations and zoom levels.
- [ ] **INT-02 · P0 · Forgiving gestures:** No essential action requires double-tapping, long-pressing, multi-finger gestures, or precision dragging. Matching activities support "tap item, then tap destination"; WCAG requires a single-pointer alternative to dragging unless an exception applies ([W3C, SC 2.5.7](https://www.w3.org/TR/WCAG22/#dragging-movements)).
- [ ] **INT-03 · P0 · Safe activation:** Activate on release, allow cancellation before release, and prevent rapid repeated taps from creating duplicate submissions. A mistaken tap can be corrected without losing the activity.
- [ ] **INT-04 · P0 · Stable controls:** Home, Back, Help, Replay, and Stop retain consistent labels and placement. No hover-only instructions; leaving an unfinished activity offers a simple, non-punitive choice.
- [ ] **INT-05 · P0 · Accessible operation:** Verify keyboard access, visible and unobscured focus, logical focus order, accessible names/roles/states, and screen-reader feedback against the applicable WCAG criteria ([W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)). Provide equivalent controls for custom learning widgets.
- [ ] **INT-06 · P0 · Feedback and latency:** Show a pressed/selected response within 100 ms on the lowest-spec supported device; show a clear loading state when processing exceeds 1 second. Measure locally rather than inferring responsiveness from network completion.
- [ ] **INT-07 · P0 · Recoverable failures:** Test interrupted requests, app restart, duplicate taps, and network loss. The interface distinguishes saved, pending, and unsaved work; never claim "Saved" without confirmation.
- [ ] **INT-08 · P0 · Shared-device boundaries:** A learner cannot open another learner's history or adult controls by changing a URL, navigating back, or selecting a roster name. Switching learners clears the previous session's visible content and protected local state.

### COPPA-oriented privacy and data security

**Primary owners:** Privacy/legal lead, security lead, engineering lead. Treat legal review and verified implementation as separate gates; a friendly interface or "parent gate" is not a substitute for either.

#### Collection, consent, and adult controls

- [ ] **PRIV-01 · P0 · Applicability decision:** Document the operator, audience, jurisdiction, data flows, and school/home use model. A service directed to children under 13 that collects personal information, or lets others collect it, falls within the FTC's stated COPPA coverage conditions ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)).
- [ ] **PRIV-02 · P0 · Data minimization:** Approve a field-by-field inventory covering app data, IP addresses, identifiers, cookies, logs, analytics, crash reports, vendors, and local caches; persistent identifiers can be personal information under COPPA ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). Proposed pilot data is limited to an assigned learner ID, required classroom linkage, activity outcomes, and necessary operational records; pseudonymous does not mean anonymous.
- [ ] **PRIV-03 · P0 · Collection gate:** Obtain verifiable parental consent before covered collection, use, or disclosure, unless a documented exception or valid school-authorization route applies ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business), [FTC school-consent guidance](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions)). Test before-consent traffic at the CDN, server, SDK, and application layers; document any narrowly justified operational collection rather than claiming "no data" from the absence of a signup form.
- [ ] **PRIV-04 · P0 · School route:** Verify the school representative's authority and document that use is for the school's educational benefit, not unrelated commercial purposes; provide the required notice and review/deletion mechanisms, and do not transfer the operator's COPPA responsibility to the school ([FTC school-consent guidance](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions)). Independent home use outside that authorization requires its own approved route.
- [ ] **PRIV-05 · P0 · Notices and records:** Publish a clear privacy policy covering collection, use, recipients, retention, contact details, and parental rights; give required direct notice and obtain renewed consent for relevant changes in previously approved practices ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). Record the notice version, scope, method, timestamp, and authorizing party without retaining unnecessary verification documents.
- [ ] **PRIV-06 · P0 · Separate disclosure choice:** If non-integral third-party disclosures are proposed, obtain separate verifiable parental consent and permit collection/internal use without that disclosure; the FTC distinguishes disclosures integral to the service ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). The pilot default is no advertising, sale, cross-context profiling, or unrelated commercial reuse.
- [ ] **PRIV-07 · P0 · Rights workflow:** An appropriately verified parent can review, request deletion, and revoke permission for further collection/use without undue burden ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). Test the workflow end to end and prevent deleted or revoked profiles from being silently recreated.
- [ ] **PRIV-08 · P0 · Adult authentication:** Protect rosters, exports, settings, and rights requests with appropriate adult authentication and authorization. A math question, "I am a parent" checkbox, or navigation gate is not treated as verifiable parental consent.
- [ ] **PRIV-09 · P0 · Additional obligations:** Legal review determines which school contracts, FERPA-related duties, state student-privacy laws, accessibility obligations, and research-consent requirements apply. Do not describe COPPA review as clearance under all applicable laws.

#### Security, vendors, and deletion

- [ ] **SEC-01 · P0 · Written security program:** Establish a documented information-security program with safeguards appropriate to the data and operation; obtain written assurances from service providers and third parties receiving children's personal information ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). Assign a responsible owner, maintain a risk register, and schedule regular control testing.
- [ ] **SEC-02 · P0 · Technical baseline:** As pilot engineering requirements, encrypt data in transit and at rest, use managed secrets, require MFA for privileged adult accounts, enforce least privilege, and patch dependencies. Test cross-school and cross-learner access controls at the API, not only the interface.
- [ ] **SEC-03 · P0 · Vendor and telemetry audit:** Inventory each SDK, endpoint, subprocessor, permission, and event property. Disable unapproved analytics, session replay, ad identifiers, and free-text payloads; test clean install, onboarding, gameplay, errors, and background activity with network capture.
- [ ] **SEC-04 · P0 · Retention schedule:** Maintain and disclose a written retention/deletion policy with specific purposes, retention needs, and deletion timeframes; do not retain children's information indefinitely or beyond what is reasonably necessary ([FTC six-step compliance plan](https://www.ftc.gov/business-guidance/resources/childrens-online-privacy-protection-rule-six-step-compliance-plan-your-business)). Set a justified trigger and duration for every data class, including consent records, logs, exports, and backups; no "TBD" periods at release.
- [ ] **SEC-05 · P0 · Verified deletion:** Demonstrate deletion propagation to production stores, processors, caches, and scheduled backup expiry. Restrict backup access and ensure a restore reapplies deletion records; retain evidence of completion without recreating the child's deleted profile.
- [ ] **SEC-06 · P0 · Incident readiness:** Approve incident ownership, containment, vendor escalation, evidence handling, and legally reviewed notification procedures. Complete a tabletop for exposed learner records and confirm the team can disable collection or revoke access promptly.

### Engagement mechanics and learning feedback

The pilot should make learning understandable and worth returning to without pressuring children to continue. All durations and reward behaviors below are proposed product rules to validate with learners and educators.

- [ ] **ENG-01 · P0 · Meaningful loop:** Each activity specifies `learning objective → model or prompt → attempt → informative feedback → retry or finish`. An educator can explain how the interaction practices the objective.
- [ ] **ENG-02 · P0 · Supportive correction:** Incorrect answers trigger a neutral, specific hint such as "Count each dot once," not shame, loss of status, or a loud failure sound. After two unsuccessful attempts, offer a worked example or adult help.
- [ ] **ENG-03 · P0 · Clear stopping points:** Show concrete progress such as "2 of 4," then a completion screen with equally clear Stop and Continue choices. No forced autoplay into another lesson or penalty for pausing.
- [ ] **ENG-04 · P0 · No coercive rewards:** No streak-loss warnings, countdown pressure, loot boxes, random reward schedules, public rankings, or messages implying that a character will be sad if the child leaves.
- [ ] **ENG-05 · P0 · Sensory safety:** Use no flashing effects; provide a reduced-motion setting and a static equivalent for celebrations. Keep proposed celebrations at or below 2 seconds, non-blocking, and dismissible; audit all animation against applicable WCAG flashing and pause requirements ([W3C, SC 2.3.1 and 2.2.2](https://www.w3.org/TR/WCAG22/)).
- [ ] **ENG-06 · P0 · Pause without punishment:** No timed response requirements in the pilot; stopping or switching to Help does not erase earned progress. Break suggestions are optional and do not shame or rank the learner.
- [ ] **ENG-07 · P1 · Limited agency:** Let children choose between two approved themes or equivalent learning activities. Cosmetic choice does not unlock additional data collection or expose paid content.
- [ ] **ENG-08 · P1 · Transparent adaptation:** Adjust task difficulty from task-relevant evidence, not inferred emotion or sensitive traits. Let teachers override level, and do not raise difficulty based solely on speed.

### Pilot validation and acceptance tests

**Proposed research plan:** Run two formative rounds, initially recruiting 5–8 learners per grade across reading levels, language backgrounds, and relevant access needs, plus 3–5 adults. Obtain appropriate adult permission and child assent; use observation notes by default, with any recording subject to separate approved consent, storage, and deletion controls.

This is a usability sample, not a statistically representative learning-efficacy study. Record counts and context, not only percentages, and do not pool grades in ways that hide a struggling subgroup.

| Test | Given / When / Then | Evidence and pass condition |
|---|---|---|
| First activity | Given completed adult setup, when a child starts, then they identify the main action and make the intended first interaction | Proposed target: at least 80% in each grade succeed after one demonstration, without an adult taking over |
| Help and recovery | Given an incorrect answer, when a child uses Help, then they understand a next step and can retry | Proposed target: at least 80% in each grade recover; log hint comprehension separately from answer correctness |
| Target usability | Given the smallest supported device, when children tap controls, then intended controls activate | Proposed target: at least 95% intended taps across observed trials; investigate recurring misses for any learner |
| No-audio path | Given muted audio, when a child navigates a non-auditory task, then they can understand the next action through visual supports | No audio-only navigation or essential feedback; auditory learning tasks use their documented accommodation path |
| Alternative input | Given keyboard or assistive technology, when an activity is completed, then focus, labels, state changes, and equivalent interactions work | Manual completion on supported assistive-technology configurations; no critical blocker |
| Consent boundary | Given no approved authorization, when the app opens or errors, then prohibited collection and SDK transmission do not occur | Network/server evidence for all startup and failure paths; only documented permitted operations remain |
| Shared device | Given learner A has finished, when learner B starts or navigates back, then A's records and adult tools are inaccessible | UI, cache, and API tests pass for cross-learner and cross-school access |
| Rights and deletion | Given a verified request, when deletion/revocation completes, then stores and processors follow the approved policy | Deletion evidence, processor confirmation, and failed attempts to resume unauthorized collection |
| Network interruption | Given an interrupted save, when connectivity returns, then work is neither duplicated nor falsely reported saved | Repeatable test on target devices, including restart and account switch |
| Safe finish | Given any activity state, when a child stops, then they can exit without guilt messaging or lost acknowledged progress | All task states pass; observe whether children can find Stop independently |

#### Learning and engagement measures

- **Task success:** Count independent starts, help use, retries, completion, and exits by grade and relevant access needs.
- **Learning signal:** Have educators select a short skill-aligned pre/post check or work-sample rubric; distinguish improvement in the practiced interface from transfer to a new example.
- **Well-being signal:** Record observed frustration, repeated confusion, refusal, and voluntary stopping; allow a child to withdraw from testing immediately.
- **Privacy-safe measurement:** Use the minimum approved event fields, avoid recordings by default, restrict report access, and avoid small-group reporting that identifies a learner.
- **Interpretation:** Establish the baseline in round one, implement fixes, and retest in round two. Do not optimize for maximum time-on-app or use raw usage as proof of learning.

### Release sign-off

- [ ] **Design:** All P0 visual, type, color, target-size, and state checks have evidence from the actual build.
- [ ] **Curriculum:** Instructional accuracy, reading demands, feedback, and accessible alternatives are approved.
- [ ] **Accessibility:** Full applicable WCAG 2.2 AA review is complete, including manual assistive-technology tests; this checklist alone is not a conformance report.
- [ ] **Privacy/legal:** The deployment model, consent route, notices, vendor practices, retention schedule, and additional legal obligations are approved.
- [ ] **Security/engineering:** No unresolved critical/high security findings; consent, authorization, isolation, and deletion tests pass.
- [ ] **Research/product:** No unresolved task-blocking pattern for a grade or access group; P1 deferrals have mitigations and dates.
- [ ] **Pilot operations:** Teacher onboarding, support contacts, rollback/collection-disable procedure, and a post-launch review date are documented.

#### Decisions required before enrollment

| Decision | Accountable owner | Blocking? |
|---|---|---|
| Exact devices, browsers, orientations, and assistive-technology support | Engineering + accessibility lead | Yes |
| School-only versus independent home use and the corresponding authorization route | Product + privacy/legal | Yes |
| Final collected fields, vendors, retention durations, and deletion verification method | Engineering + privacy/security | Yes |
| Pilot learning objectives, learner languages, and accommodation coverage | Curriculum + research | Yes |
| Optional themes and cosmetic reward variations | Design | No; omit if unresolved |

**Go/no-go rule:** Release only when every applicable P0 check passes and each required owner signs off. If a safety, privacy, security, or accessibility issue cannot be resolved, remove the affected feature or postpone the pilot rather than relying on child or teacher workarounds.
