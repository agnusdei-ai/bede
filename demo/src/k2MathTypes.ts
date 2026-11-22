export type CounterColor = 'red' | 'yellow'
export interface CountersPiece { kind: 'counters'; groups: { color: CounterColor; count: number }[] }
export interface TenFramePiece { kind: 'ten_frame'; frames?: number; red?: number; yellow?: number; crossed?: number }
export interface NumberBondPiece { kind: 'number_bond'; whole: number | null; parts: (number | null)[] }
/** Plates of counters (grade 2): `groups` plates with `each` on every one,
 * or `loose` counters still to be shared out onto empty plates. */
export interface EqualGroupsPiece { kind: 'equal_groups'; groups: number; each?: number; loose?: number }
export type MathPiece = CountersPiece | TenFramePiece | NumberBondPiece | EqualGroupsPiece

export interface MathTask {
  phase?: 'together' | 'your_turn'
  index?: number
  prompt: { key: string; args: Record<string, string> }
  display: { diagram: MathPiece; guide: boolean; ghost?: number }
  choice_kind: 'number' | 'color' | 'build'
  choices: string[]
  build?: { start: number; capacity: number; take_away: boolean }
}

export interface MathLesson {
  lesson_id: string
  area: 'math'
  level: 'K' | '1' | '2'
  topic: string
  skill: string
  your_turn_tries: number
  available_topics?: string[]
  audio?: boolean
  needs_audio?: boolean
  watch: (MathTask & { answer: { choice: string } }) | null
  together: MathTask[]
  your_turn: MathTask[]
}

export interface MathPracticeAnswer {
  understood: boolean
  correct: boolean
  reveal?: { choice: string }
}

export interface MathPracticeTransport {
  load: (audio: boolean, topic?: string) => Promise<MathLesson>
  answer: (
    lessonId: string,
    phase: 'together' | 'your_turn',
    index: number,
    choice: string,
    submissionId: string,
  ) => Promise<MathPracticeAnswer>
}
