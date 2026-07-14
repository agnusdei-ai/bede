/**
 * Bug-catcher: multi-turn conversation-flow scenarios against the REAL
 * sessionStore (no mocks of the code under test). Simulates exactly what
 * SocraticChat.tsx does per SSE chunk, then inspects the history that
 * would be sent to POST /tutor/chat on the next turn.
 */
// sessionStorage polyfill for the zustand persist middleware
const mem = new Map<string, string>()
;(globalThis as any).sessionStorage = {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => void mem.set(k, v),
  removeItem: (k: string) => void mem.delete(k),
}

const { useSessionStore, getApiMessages } = await import('../src/store/sessionStore')

const store = useSessionStore
const S = () => store.getState()

type Chunk =
  | { type: 'text'; content: string }
  | { type: 'tool'; tool: string; content: string }
  | { type: 'visual_aid'; title: string }

// Mirrors consumeTurnStream in SocraticChat.tsx
function bedeTurn(chunks: Chunk[], opts: { viaUserSend?: boolean } = {}) {
  if (!opts.viaUserSend) S().startAssistantStream()
  for (const c of chunks) {
    if (c.type === 'text') S().appendAssistantChunk(c.content)
    else if (c.type === 'tool') S().addToolMessage(c.tool, c.content)
    else S().addVisualAidMessage({ visual_aid_id: 'x', title: c.title, artist: 'Millet', caption: '', image_query: '' } as any)
  }
  S().finalizeAssistantMessage()
  S().setStreaming(false)
}

// Mirrors send() in SocraticChat.tsx: history snapshot BEFORE addUserMessage
function childSend(msg: string, drawing = false) {
  const fullMsg = drawing ? (msg ? msg + ' ' : '') + '[✏️ Drawing]' : msg
  const apiHistory = getApiMessages(S().displayMessages, S().subjectStart)
  S().addUserMessage(fullMsg)
  // what the backend builds: history + the new user message
  return [...apiHistory.map((m) => ({ role: m.role, content: m.content })), { role: 'user', content: fullMsg }]
}

function bubbleTranscript() {
  return S().displayMessages
    .filter((m) => m.id !== 'streaming-response')
    .map((m) => `${m.role}${m.tool ? `/${m.tool}` : (m as any).visualAid ? '/visual_aid' : ''}: ${JSON.stringify(m.content).slice(0, 60)}`)
}

const findings: string[] = []
function check(name: string, cond: boolean, detail: string) {
  if (cond) findings.push(`[DEFECT] ${name}: ${detail}`)
  else console.log(`  ok — ${name}`)
}

function apiView(msgs: { role: string; content: string }[]) {
  return msgs.map((m) => `    ${m.role}: ${JSON.stringify(m.content)}`).join('\n')
}

// ── Setup: real session with two subjects ───────────────────────────────────
store.setState({
  sessionConfig: {
    student_name: 'Emma', grade: '4', grade_stage: '4-6',
    subjects: ['art_music', 'mathematics'], voice_required: false,
  } as any,
  token: 't',
})
S().startSession()

// ── S1: Picture-study turn (the reported bug) ───────────────────────────────
console.log('\nS1: picture study — show painting + ask to describe, child answers')
bedeTurn([
  { type: 'text', content: 'Today we look at a painting together. ' },
  { type: 'visual_aid', title: 'The Angelus' },
  { type: 'tool', tool: 'request_narration', content: '📖 Look closely for a while. When the picture is put away, tell me everything you remember seeing.' },
])
const s1 = childSend('Two farmers are praying in a field at sunset.')
console.log(apiView(s1))
check('S1a empty assistant message sent to API', s1.some((m) => m.content === ''), 'visual-aid message passes the filter as role=assistant content="" — Messages API rejects empty content mid-conversation')
check('S1b Bede\'s ask missing from history', !s1.some((m) => m.content.includes('tell me everything you remember')), 'the request_narration card (the actual question) never reaches the model')
check('S1c no record a painting was shown', !s1.some((m) => m.content.includes('Angelus')), 'model has no memory of which painting (or that any) was shown → re-shows and re-asks')

// ── S2: Tool-only turn (hint delivered as card, no plain text) ───────────────
console.log('\nS2: Bede turn that is ONLY tool cards (hint), child answers')
bedeTurn([{ type: 'tool', tool: 'offer_socratic_hint', content: '🔍 Think about what the church bell in the distance might mean.' }], { viaUserSend: true })
const s2 = childSend('Maybe they stopped working to pray when the bell rang?')
console.log(apiView(s2.slice(-3)))
const lastThree = s2.slice(-3)
check('S2 two consecutive user messages, assistant turn vanished', lastThree.filter((m) => m.role === 'user').length >= 2 && !lastThree.some((m) => m.content.includes('church bell')), 'the hint the child is answering does not exist in the transcript the model sees')

// ── S3: Drawing-only send ────────────────────────────────────────────────────
// This check still fires below — by design, not a leftover bug. The real
// fix for this one lives server-side (homeschool-api/services/ai_service.py's
// sacred_rules #12: Bede is now required to name a specific, genuine detail
// from any drawing/handwriting it can see in its own reply — since the
// image itself is never resent on later turns, Bede's own words there are
// the only durable record of what it showed, and THAT is what carries
// forward through normal conversation history). Nothing at this layer
// (getApiMessages/sessionStore) can observe that fix, since it's about what
// the model chooses to say, not how this store shapes history — so this
// check keeps flagging the placeholder itself as content-free, which is
// still literally true, just no longer the whole picture.
console.log('\nS3: child sends a drawing with no text')
bedeTurn([{ type: 'text', content: 'Can you sketch the two figures from memory?' }], { viaUserSend: true })
const s3 = childSend('', true)
console.log(apiView(s3.slice(-2)))
check('S3 later turns keep only "[✏️ Drawing]" placeholder', s3.at(-1)!.content === '[✏️ Drawing]', 'the image goes to the API once (this turn); every later turn sees a bare placeholder with no description of what was drawn — see this block\'s own comment above for where the real fix actually lives')

// ── S4: suggest_next_subject on the LAST subject ────────────────────────────
console.log('\nS4: advance past the final subject (suggest_next_subject fires on last subject)')
S().nextSubject() // art_music -> mathematics
bedeTurn([{ type: 'text', content: 'Let us count by threes. What comes after 3, 6, 9?' }])
childSend('12!')
bedeTurn([{ type: 'text', content: 'Exactly right, 12. ' }, { type: 'tool', tool: 'subject_complete', content: 'Wonderful work — let us move on!' }], { viaUserSend: true })
S().nextSubject() // past the end — what happens?
const st = S()
console.log(`    currentSubject=${st.currentSubject} idx=${st.currentSubjectIndex} subjectStart=${st.subjectStart} msgs=${st.displayMessages.length}`)
const s4 = childSend('What should we do now?')
console.log(apiView(s4))
check('S4 stuck on last subject with amnesia', st.currentSubject === 'mathematics' && s4.length === 1, 'past the last subject the session stays on the same subject but subjectStart advances — all math context is wiped while the child keeps chatting')

// ── S5: [CONTINUE] idle sentinel not recorded ───────────────────────────────
// This check still fires below — by design, not a leftover bug. What it
// finds here (consecutive assistant-role turns reaching the API) is a real,
// accurate description of what getApiMessages/sessionStore produce, and
// that part is left as-is deliberately: the [CONTINUE] sentinel genuinely
// shouldn't become a visible user bubble. The actual danger this posed —
// the Messages API rejects two same-role turns in a row outright — is fixed
// one layer downstream instead, in
// homeschool-api/services/ai_service.py's _normalize_alternating_roles(),
// applied to both stream_tutor_response and stream_sandbox_response right
// before the API call. See tests/test_normalize_alternating_roles.py and
// tests/test_stream_history_normalization.py on the backend for the real
// regression coverage; nothing at this frontend layer can observe that fix.
console.log('\nS5: idle CONTINUE sentinel → next turn history')
// [CONTINUE] is sent to the API but never stored as a user bubble (by design);
// Bede's reply IS stored. Simulate reply then child speaks.
bedeTurn([{ type: 'text', content: 'Are you still there? Here is an easier way to think about it.' }])
const s5 = childSend('Sorry, I am back!')
const assistantRuns = s5.reduce((acc: number[], m, i) => (m.role === 'assistant' && s5[i - 1]?.role === 'assistant' ? [...acc, i] : acc), [])
console.log(apiView(s5))
check('S5 consecutive assistant messages after auto-continue', assistantRuns.length > 0, 'the model sees itself speak twice with no user turn between — see this block\'s own comment above for why this is expected and handled server-side, not a leftover bug')

// ── Summary ─────────────────────────────────────────────────────────────────
console.log('\n──── displayMessages (what the CHILD saw) ────')
bubbleTranscript().forEach((l) => console.log('  ' + l))
console.log('\n──── FINDINGS ────')
if (findings.length === 0) console.log('no defects found')
findings.forEach((f) => console.log(f))
