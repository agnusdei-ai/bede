// Suggestions shown during the mandatory eye-rest break, to nudge screen time
// toward something other than another screen. Picked deterministically by
// cycle index so the suggestion stays put for the duration of one break
// instead of changing every re-render.

export interface BreakActivity {
  category: 'eyes' | 'mental_math' | 'movement' | 'word_play' | 'nature' | 'faith'
  prompt: string
}

// The break exists to be with nature, rest the eyes, or reflect on God —
// so the rotation leans on those three, with movement/mental refreshers
// mixed in. Interleaved (not grouped) so consecutive breaks in one long
// session land on different kinds of rest.
export const BREAK_ACTIVITIES: BreakActivity[] = [
  { category: 'eyes', prompt: 'Look at something at least 20 feet away for 20 seconds — it gives your eyes a real rest.' },
  { category: 'nature', prompt: 'Step outside if you can — find one living thing (a bird, a leaf, an insect) and really look at it for a minute.' },
  { category: 'faith', prompt: 'Take a quiet moment to thank God for one thing you learned or noticed today.' },
  { category: 'movement', prompt: 'Do 15 jumping jacks or stretch your arms up over your head.' },
  { category: 'nature', prompt: 'Look out a window at the sky. What are the clouds doing right now? Which way is the wind blowing?' },
  { category: 'mental_math', prompt: 'Mental math: what is 17 + 26? Try it without writing it down.' },
  { category: 'faith', prompt: 'Pray a slow Our Father, paying attention to one phrase you usually rush past.' },
  { category: 'word_play', prompt: 'Name five animals whose names start with the letter B.' },
  { category: 'nature', prompt: 'Find something outside worth drawing later — remember it for your nature notebook.' },
  { category: 'movement', prompt: 'Walk to another room and back before you sit down again.' },
  { category: 'eyes', prompt: 'Close your eyes gently and roll your shoulders back ten times.' },
  { category: 'faith', prompt: 'Sit still for one quiet minute. God speaks in the silence — just listen.' },
  { category: 'mental_math', prompt: 'Mental math: what is 9 x 7? Say the answer out loud.' },
  { category: 'word_play', prompt: 'Think of a word that rhymes with "light" — how many can you find?' },
  { category: 'movement', prompt: 'Step outside or to a window and take five slow, deep breaths.' },
  { category: 'mental_math', prompt: 'Mental math: if you have 3 dozen eggs, how many eggs is that?' },
]

export function pickBreakActivity(cycleIndex: number): BreakActivity {
  return BREAK_ACTIVITIES[cycleIndex % BREAK_ACTIVITIES.length]
}
