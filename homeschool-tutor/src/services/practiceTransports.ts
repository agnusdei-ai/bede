// The household app's Sound Time and Map Practice transports: the signed-in
// learner's own rounds through the household API, which records progress.
// The public demo supplies its own temporary, unrecorded transports instead.
import { answerMapTask, answerPhonicsTask, fetchMapLesson, fetchPhonicsLesson } from './api'
import type { PhonicsPracticeTransport } from './k2PhonicsTypes'
import type { MapPracticeTransport } from './mapPracticeTypes'

export function phonicsTransport(token: string, studentName: string): PhonicsPracticeTransport {
  return {
    load: (audio) => fetchPhonicsLesson(token, studentName, audio),
    answer: (lessonId, phase, index, choice) => answerPhonicsTask(token, studentName, lessonId, phase, index, { choice }),
  }
}

export function mapTransport(token: string, studentName: string): MapPracticeTransport {
  return {
    load: () => fetchMapLesson(token, studentName),
    answer: (lessonId, phase, index, answer) => answerMapTask(token, studentName, lessonId, phase, index, answer),
  }
}
