/**
 * The mastery cycle — the cadence between "today's session summary" and
 * "the whole term".
 *
 * A term is 9-12 weeks, which is too coarse to answer "is this on track?",
 * and the learner's guarantee is written in 30 days. Before this there was
 * nothing in between: Progress.tsx's term outcomes took the best level EVER
 * recorded for a topic, with no time window at all, so an assessment from
 * ten weeks ago counted exactly as much as one from yesterday. That read
 * cannot answer "did this move recently", which is the question a parent
 * actually has.
 *
 * WHAT IS BOUNDED IS THE LOOKING, NOT THE CHILD'S WORK. A sprint commits
 * that scope will be finished by a date; pointed at a child that is a
 * deadline on a person, which contradicts the standing rule never to hurry,
 * time, or mention pace to a child. So this window carries no deadline and
 * no target. It is deliberately ROLLING rather than a numbered cycle with a
 * start date: there is no boundary to hit, nothing resets, nothing rolls
 * over, and no velocity can be computed across cycles. That is also what
 * keeps it honest about learning being open-ended — a rolling window has no
 * end to fail to meet.
 *
 * The three outcomes are not pass/fail, and the third is the load-bearing
 * one: `no_evidence` is a finding about the PLAN, not about the child. It
 * means the subject wasn't scheduled often enough, or the topic never came
 * up — the same discipline the work ledger already holds, where unscored
 * work must never render as low-scored work.
 */
import type { NarrationAssessmentData } from '../types'

/** Mirrors models/schemas.py's DEFAULT_MASTERY_CYCLE_DAYS — four ACTUAL
 *  weeks, the same window the learner's guarantee is written against. */
export const DEFAULT_MASTERY_CYCLE_DAYS = 28

export type TopicLevel = 'introduced' | 'developing' | 'mastered'

/** Ordinal rank. Deliberately not exported as a score — see `summarize`'s
 *  own refusal to average an ordinal scale; these compare, they don't add. */
const LEVEL_RANK: Record<TopicLevel, number> = {
  introduced: 1,
  developing: 2,
  mastered: 3,
}

export type CycleOutcome =
  /** Real evidence the child advanced within the window. */
  | 'moved'
  /** Worked within the window, no visible movement yet. Normal, not a fault. */
  | 'held'
  /** Nothing recorded in the window. About the plan, never about the child. */
  | 'no_evidence'

export interface CycleRead {
  outcome: CycleOutcome
  /** Best level reached at any point, including before the window. */
  now: TopicLevel | null
  /** Best level as of the window's start — what `now` is measured against. */
  atWindowStart: TopicLevel | null
  /** How many assessments landed inside the window. */
  countInWindow: number
}

const higher = (a: TopicLevel | null, b: TopicLevel | null): TopicLevel | null => {
  if (!a) return b
  if (!b) return a
  return LEVEL_RANK[b] > LEVEL_RANK[a] ? b : a
}

/**
 * Read one topic against the rolling window.
 *
 * `now` is a high-water mark across all time and never decays — a child who
 * demonstrated mastery in week two has demonstrated it, and the window does
 * not take that away. What the window changes is only whether we say it
 * MOVED, which is a claim about the last N days.
 */
export function readCycle(
  assessments: readonly NarrationAssessmentData[],
  topic: string,
  windowDays: number,
  now: Date = new Date(),
): CycleRead {
  const cutoff = now.getTime() - windowDays * 24 * 60 * 60 * 1000

  let atWindowStart: TopicLevel | null = null
  let latest: TopicLevel | null = null
  let countInWindow = 0

  for (const a of assessments) {
    if (a.term_topic !== topic || !a.term_topic_level) continue
    const at = Date.parse(a.assessed_at)
    // An unparseable timestamp counts toward the standing picture but never
    // toward "moved recently" — claiming movement we can't date would be
    // worse than staying quiet about it.
    if (Number.isNaN(at)) {
      latest = higher(latest, a.term_topic_level)
      continue
    }
    latest = higher(latest, a.term_topic_level)
    if (at >= cutoff) countInWindow += 1
    else atWindowStart = higher(atWindowStart, a.term_topic_level)
  }

  if (countInWindow === 0) {
    return { outcome: 'no_evidence', now: latest, atWindowStart, countInWindow }
  }

  const advanced =
    latest !== null &&
    (atWindowStart === null || LEVEL_RANK[latest] > LEVEL_RANK[atWindowStart])

  return {
    outcome: advanced ? 'moved' : 'held',
    now: latest,
    atWindowStart,
    countInWindow,
  }
}

/** Whole weeks when it divides evenly, else days — "4 weeks" reads better
 *  than "28 days", but "25 days" must not silently become "3 weeks". */
export function describeWindow(days: number): { value: number; unit: 'week' | 'day' } {
  return days % 7 === 0 ? { value: days / 7, unit: 'week' } : { value: days, unit: 'day' }
}
