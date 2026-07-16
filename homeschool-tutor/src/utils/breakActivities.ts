// Suggestions shown during the mandatory eye-rest break, to nudge screen time
// toward something other than another screen. Picked deterministically by
// cycle index so the suggestion stays put for the duration of one break
// instead of changing every re-render.
//
// Prompt TEXT lives in i18n/locales/{en,es}.json's `breakActivities` array
// (index-aligned with CATEGORIES below) rather than here, so it switches
// language with the rest of the UI — see TutorSession.tsx's call site,
// which resolves the text via t('breakActivities', { returnObjects: true }).

export type BreakActivityCategory = 'eyes' | 'mental_math' | 'movement' | 'word_play' | 'nature' | 'faith'

export interface BreakActivity {
  category: BreakActivityCategory
  index: number
}

// The break exists to be with nature, rest the eyes, or reflect on God —
// so the rotation leans on those three, with movement/mental refreshers
// mixed in. Interleaved (not grouped) so consecutive breaks in one long
// session land on different kinds of rest. Order/length must stay in sync
// with both locale files' `breakActivities` arrays — index i here IS
// breakActivities[i] in en.json/es.json.
const CATEGORIES: BreakActivityCategory[] = [
  'eyes', 'nature', 'faith', 'movement', 'nature', 'mental_math', 'faith', 'word_play',
  'nature', 'movement', 'eyes', 'faith', 'mental_math', 'word_play', 'movement', 'mental_math',
]

export function pickBreakActivity(cycleIndex: number): BreakActivity {
  const index = cycleIndex % CATEGORIES.length
  return { category: CATEGORIES[index], index }
}
