// Wire types for K-2 Sound Time (homeschool-api/services/k2_practice/phonics.py).
// Shared, byte for byte, with the public demo's copy (demo/src/k2PracticeParity.test.ts).

export interface PhonicsGrapheme { text: string; sound?: string; silent?: boolean }

export interface PhonicsTask {
  phase?: 'together' | 'your_turn'
  index?: number
  prompt: { key: string; args: Record<string, string> }
  /** A picture to hear, a word to read, or a word to listen for. In "Your
   * turn", a word to read carries no sounds and no spoken word. */
  display: { kind: 'picture' | 'word' | 'listen' | 'none'; icon?: string; word?: string; graphemes?: PhonicsGrapheme[] }
  choice_kind: 'picture' | 'letter' | 'word'
  choices: string[]
  /** Sounds for tapping a letter choice. Never sent in "Your turn". */
  choice_sounds?: Record<string, string>
}

export interface PhonicsLesson {
  lesson_id: string
  area: 'phonics'
  level: 'K' | '1' | '2'
  domain: string
  your_turn_tries: number
  /** Whether the lesson was built for a device that can speak it. */
  audio?: boolean
  /** The child's practice works only by ear and the device cannot speak, so
   * the lesson has no questions (sight words). Nothing can be recorded. */
  needs_audio?: boolean
  watch: (PhonicsTask & { answer: { choice: string } }) | null
  together: PhonicsTask[]
  your_turn: PhonicsTask[]
}

export interface PhonicsAnswerResult {
  understood: boolean
  correct: boolean
  tries_left?: number
  reveal?: { choice: string }
  recorded?: boolean
}

/** Where a round comes from and where its answers go: the household API, or
 * the public demo's temporary, unrecorded rounds. */
export interface PhonicsPracticeTransport {
  load: (audio: boolean) => Promise<PhonicsLesson>
  answer: (lessonId: string, phase: 'together' | 'your_turn', index: number, choice: string) => Promise<PhonicsAnswerResult>
}
