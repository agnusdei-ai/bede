/**
 * Pure helpers for teacher quizzes with reviewable answer keys
 * (docs/PRACTICE_COACH.md, "Teacher quizzes with answer keys").
 *
 * Two rules live here because the screen applies them on every edit:
 *
 * - Any edit un-approves the quiz. An approved key is approved as it stood;
 *   a changed one has to be checked again by the server.
 * - Typing an answer makes it the teacher's own. A suggested or page-read
 *   answer stays unapproved until the teacher presses "Looks right".
 *
 * The server checks the key again before scoring regardless, so these keep
 * the screen honest rather than standing in for the server.
 */
import type { GeneratedQuiz, ProposedScore, TeacherQuestion, TeacherQuiz } from '../services/api'

export const TEACHER_QUIZ_FORMAT = 'bede.teacher-quiz'

export function blankQuestion(number: number): TeacherQuestion {
  return {
    number, type: 'short_answer', prompt: '', options: [], answer: '', accepted_answers: [],
    rubric: null, scoring_guidance: null, points: 1, key_source: 'teacher', key_approved: true,
    answer_check: null, reading_note: null,
  }
}

export function blankQuiz(subject: string, grade: string, title: string): TeacherQuiz {
  return { format: TEACHER_QUIZ_FORMAT, version: 1, title, subject, grade, questions: [blankQuestion(1)], approved: false }
}

/** A quiz Bede drafted becomes a teacher quiz whose every answer is Bede's
 *  suggestion, unapproved. A disagreeing second check becomes a note to settle. */
export function fromGenerated(quiz: GeneratedQuiz): TeacherQuiz {
  return {
    format: TEACHER_QUIZ_FORMAT, version: 1, title: quiz.title, subject: quiz.subject, grade: quiz.grade,
    approved: false,
    questions: quiz.questions.map((q, i) => ({
      number: i + 1, type: q.type, prompt: q.prompt, options: q.options, answer: q.answer,
      accepted_answers: [], rubric: null, scoring_guidance: null, points: 1,
      key_source: 'bede', key_approved: false, answer_check: q.answer_check,
      reading_note: q.second_answer ? `A second check answered: ${q.second_answer}` : null,
    })),
  }
}

function renumber(questions: TeacherQuestion[]): TeacherQuestion[] {
  return questions.map((q, i) => ({ ...q, number: i + 1 }))
}

export function editQuestion(quiz: TeacherQuiz, index: number, patch: Partial<TeacherQuestion>): TeacherQuiz {
  const questions = quiz.questions.map((q, i) => {
    if (i !== index) return q
    const next = { ...q, ...patch }
    if ('answer' in patch || 'rubric' in patch || 'accepted_answers' in patch) {
      next.key_source = 'teacher'
      next.key_approved = true
      next.answer_check = null
    }
    if (next.type === 'true_false') next.options = ['True', 'False']
    return next
  })
  return { ...quiz, questions, approved: false }
}

/** "Looks right": the teacher accepts the reading and the answer as they stand. */
export function settleQuestion(quiz: TeacherQuiz, index: number): TeacherQuiz {
  return {
    ...quiz,
    approved: false,
    questions: quiz.questions.map((q, i) => i === index ? { ...q, key_approved: true, reading_note: null } : q),
  }
}

export function addQuestion(quiz: TeacherQuiz): TeacherQuiz {
  return { ...quiz, approved: false, questions: [...quiz.questions, blankQuestion(quiz.questions.length + 1)] }
}

export function removeQuestion(quiz: TeacherQuiz, index: number): TeacherQuiz {
  if (quiz.questions.length <= 1) return quiz
  return { ...quiz, approved: false, questions: renumber(quiz.questions.filter((_, i) => i !== index)) }
}

/** Whether the screen should ask the teacher to look at this question. */
export function needsLook(q: TeacherQuestion): boolean {
  const hasKey = q.answer.trim() !== '' || (q.rubric ?? '').trim() !== ''
  return !!q.reading_note || (hasKey && !q.key_approved)
}

export function exportFile(quiz: TeacherQuiz): string {
  return JSON.stringify(quiz, null, 2)
}

/** A file the teacher saved earlier. The server checks its shape again on import. */
export function parseImport(text: string): TeacherQuiz | null {
  try {
    const data = JSON.parse(text)
    if (!data || data.format !== TEACHER_QUIZ_FORMAT || !Array.isArray(data.questions)) return null
    return data as TeacherQuiz
  } catch {
    return null
  }
}

/** A result counts only once settled. Bede's proposal settles nothing that
 *  was marked for the teacher; everything else starts at Bede's proposal and
 *  the teacher can still change it. */
export function initialSettlement(results: ProposedScore[]): Record<number, number | null> {
  return Object.fromEntries(results.map((r) => [r.number, r.needs_teacher ? null : r.proposed_points]))
}

export function allSettled(settled: Record<number, number | null>, results: ProposedScore[]): boolean {
  return results.every((r) => typeof settled[r.number] === 'number')
}
