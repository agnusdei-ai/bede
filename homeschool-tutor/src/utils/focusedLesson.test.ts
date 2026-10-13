import { describe, expect, it } from 'vitest'
import type { SessionConfig } from '../types'
import { prepareFocusedLesson } from './focusedLesson'

const student: SessionConfig = {
  student_name: 'Avery',
  grade: '4',
  grade_stage: '3-5',
  subjects: ['living_books', 'mathematics', 'history'],
  companion_mode: 'guided',
  current_unit: 'Ancient Egypt',
  lesson_focus: 'Earlier plan',
  lesson_resume: [
    { subject: 'mathematics', stopped_at: 'Fractions, lesson 2', next_step: 'Compare halves' },
    { subject: 'history', stopped_at: 'The Nile' },
  ],
  voice_required: true,
  learning_support: ['Use smaller questions'],
  term_mastery_topics: { reading_literature: ['Narration'] },
}

describe('parent-led focused lesson', () => {
  it('narrows only to an already approved subject, preserving protections and academic context', () => {
    const lesson = prepareFocusedLesson(student, 'mathematics', '  Compare fraction sizes  ')
    expect(lesson?.subjects).toEqual(['mathematics'])
    expect(lesson?.lesson_focus).toBe('Compare fraction sizes')
    expect(lesson?.lesson_resume).toEqual([student.lesson_resume?.[0]])
    expect(lesson?.voice_required).toBe(true)
    expect(lesson?.learning_support).toEqual(student.learning_support)
    expect(lesson?.term_mastery_topics).toEqual(student.term_mastery_topics)
    expect(student.subjects).toEqual(['living_books', 'mathematics', 'history'])
    expect(student.lesson_focus).toBe('Earlier plan')
  })

  it('rejects any subject outside the parent-approved curriculum', () => {
    expect(prepareFocusedLesson(student, 'latin', 'Please add Latin')).toBeNull()
  })

  it('does not inherit an irrelevant old focus when the parent leaves this lesson focus empty', () => {
    expect(prepareFocusedLesson(student, 'mathematics', '  ')?.lesson_focus).toBeUndefined()
    expect(student.lesson_focus).toBe('Earlier plan')
  })

  it('limits a handwritten focus to the existing server field length', () => {
    expect(prepareFocusedLesson(student, 'mathematics', 'a'.repeat(900))?.lesson_focus).toHaveLength(300)
  })
})
