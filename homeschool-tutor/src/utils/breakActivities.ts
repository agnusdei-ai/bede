// Suggestions shown during the mandatory eye-rest break, to nudge screen time
// toward something other than another screen. Picked deterministically by
// cycle index so the suggestion stays put for the duration of one break
// instead of changing every re-render.

export interface BreakActivity {
  category: 'eyes' | 'mental_math' | 'movement' | 'word_play'
  prompt: string
}

export const BREAK_ACTIVITIES: BreakActivity[] = [
  { category: 'eyes', prompt: 'Look at something at least 20 feet away for 20 seconds — it gives your eyes a real rest.' },
  { category: 'mental_math', prompt: 'Mental math: what is 17 + 26? Try it without writing it down.' },
  { category: 'movement', prompt: 'Do 15 jumping jacks or stretch your arms up over your head.' },
  { category: 'word_play', prompt: 'Name five animals whose names start with the letter B.' },
  { category: 'mental_math', prompt: 'Mental math: what is 9 x 7? Say the answer out loud.' },
  { category: 'movement', prompt: 'Walk to another room and back before you sit down again.' },
  { category: 'eyes', prompt: 'Close your eyes gently and roll your shoulders back ten times.' },
  { category: 'word_play', prompt: 'Think of a word that rhymes with "light" — how many can you find?' },
  { category: 'mental_math', prompt: 'Mental math: if you have 3 dozen eggs, how many eggs is that?' },
  { category: 'movement', prompt: 'Step outside or to a window and take five slow, deep breaths.' },
]

export function pickBreakActivity(cycleIndex: number): BreakActivity {
  return BREAK_ACTIVITIES[cycleIndex % BREAK_ACTIVITIES.length]
}
