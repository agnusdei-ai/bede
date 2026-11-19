// Wire types for K-2 Map Practice (homeschool-api/services/map_practice.py).
// Shared, byte for byte, with the public demo's copy (demo/src/k2PracticeParity.test.ts).

export type MapCell = [number, number]

export interface MapScene {
  cols: number
  rows: number
  style: 'picture' | 'map'
  items: { symbol: string; col: number; row: number }[]
  water: MapCell[]
  path: MapCell[]
  compass: 'none' | 'north_only' | 'labeled'
  grid_labels: boolean
  key: boolean
}

export interface MapTask {
  phase?: 'together' | 'your_turn'
  index?: number
  scene: MapScene
  prompt: { key: string; args: Record<string, string | number | number[]> }
  answer_kind: 'tap' | 'choice' | 'scene_choice'
  choices?: string[]
  options?: MapScene[]
  side_view?: string[]
  marked?: MapCell
  guide_cells?: MapCell[]
}

export interface MapReveal { cell?: MapCell; choice?: string }

export interface MapLesson {
  lesson_id: string
  level: 'K' | '1' | '2'
  skill: string
  your_turn_tries: number
  watch: MapTask & { answer: MapReveal }
  together: MapTask[]
  your_turn: MapTask[]
}

export interface MapAnswerResult {
  understood: boolean
  correct: boolean
  tries_left?: number
  reveal?: MapReveal
  recorded?: boolean
}

export type MapAnswer = { cell: MapCell } | { choice: string }

/** Where a round comes from and where its answers go: the household API, or
 * the public demo's temporary, unrecorded rounds. */
export interface MapPracticeTransport {
  load: () => Promise<MapLesson>
  answer: (lessonId: string, phase: 'together' | 'your_turn', index: number, answer: MapAnswer) => Promise<MapAnswerResult>
}
