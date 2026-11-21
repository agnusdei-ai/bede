/**
 * The rules for taking a drafted quiz one question at a time: whether an
 * answer is right, and which question comes next.
 *
 * Mirrored byte for byte (below this header) in demo/src/quizRunner.ts;
 * demo/src/quizRunner.test.ts imports both and asserts they agree.
 *
 * Checking is deliberately narrow. A choice, true/false or number answer is
 * checked in code. Any other answer that does not match the key exactly is
 * `open`: the answer is shown and the adult decides, and it never moves the
 * difficulty, because a wording difference is not evidence of a miss.
 *
 * Adapting: the quiz starts on level. A right answer steps the next question
 * up one level, a miss steps it down, an `open` answer stays. When no
 * question is left at the target level, the nearest level is used.
 */

export type QuizDifficulty = 'easier' | 'on' | 'harder'
export type QuizResult = 'right' | 'wrong' | 'open'

export interface RunnableQuestion {
  type: string
  prompt: string
  options: string[]
  answer: string
  explanation?: string
  difficulty?: QuizDifficulty
}

const LEVELS: QuizDifficulty[] = ['easier', 'on', 'harder']

export function normalizeAnswer(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9./\-\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** A plain number, a fraction (3/4) or a mixed number (1 1/2), else null. */
export function parseNumber(text: string): number | null {
  const t = text.replace(/,/g, '').replace(/\s*=\s*$/, '').trim()
  let m = t.match(/^(-?\d+)\s+(\d+)\/(\d+)$/)
  if (m && Number(m[3]) !== 0) {
    const whole = Number(m[1])
    const part = Number(m[2]) / Number(m[3])
    return whole < 0 ? whole - part : whole + part
  }
  m = t.match(/^(-?\d+(?:\.\d+)?)\/(\d+(?:\.\d+)?)$/)
  if (m && Number(m[2]) !== 0) return Number(m[1]) / Number(m[2])
  m = t.match(/^-?\d+(?:\.\d+)?$/)
  return m ? Number(t) : null
}

/** The option a response names: its text, or its letter (A, b), else null. */
function chosenOption(question: RunnableQuestion, response: string): string | null {
  const said = normalizeAnswer(response)
  const byText = question.options.find((o) => normalizeAnswer(o) === said)
  if (byText) return byText
  const letter = response.trim().match(/^\(?([a-f])[).:]?$/i)
  if (letter) return question.options[letter[1].toLowerCase().charCodeAt(0) - 97] ?? null
  return null
}

export function checkAnswer(question: RunnableQuestion, response: string): QuizResult {
  if (!response.trim()) return 'open'
  if (question.type === 'written_response') return 'open'
  if (question.options.length) {
    const chosen = chosenOption(question, response)
    if (chosen === null) return 'open'
    return normalizeAnswer(chosen) === normalizeAnswer(question.answer) ? 'right' : 'wrong'
  }
  const key = parseNumber(question.answer.split(' (=')[0])
  const given = parseNumber(response)
  if (key !== null && given !== null) return Math.abs(key - given) < 1e-9 ? 'right' : 'wrong'
  if (key !== null && question.type === 'computation') return 'wrong'
  return normalizeAnswer(response) === normalizeAnswer(question.answer) ? 'right' : 'open'
}

export function stepLevel(level: QuizDifficulty, result: QuizResult): QuizDifficulty {
  const at = LEVELS.indexOf(level)
  if (result === 'right') return LEVELS[Math.min(at + 1, LEVELS.length - 1)]
  if (result === 'wrong') return LEVELS[Math.max(at - 1, 0)]
  return level
}

/** The next unanswered question nearest the target level, in draft order. */
export function nextQuestion(
  questions: RunnableQuestion[], answered: ReadonlySet<number>, target: QuizDifficulty,
): number | null {
  const want = LEVELS.indexOf(target)
  let best: number | null = null
  let bestDistance = Infinity
  questions.forEach((q, index) => {
    if (answered.has(index)) return
    const distance = Math.abs(LEVELS.indexOf(q.difficulty ?? 'on') - want)
    if (distance < bestDistance) {
      best = index
      bestDistance = distance
    }
  })
  return best
}
