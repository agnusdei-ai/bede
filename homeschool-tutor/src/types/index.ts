import { Sun, BookOpen, Calculator, Leaf, Globe, PenLine, FlaskConical, Palette, Star, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type GradeStage = 'K-2' | '3-5' | '6-8'

export type Subject =
  | 'morning_time'
  | 'living_books'
  | 'mathematics'
  | 'nature_study'
  | 'history'
  | 'language_arts'
  | 'science'
  | 'art_music'
  | 'saints'
  | 'free_study'

export interface SessionConfig {
  student_name: string
  grade: string
  grade_stage: GradeStage
  subjects: Subject[]
  lesson_focus?: string
  faith_emphasis?: string
  current_unit?: string
  voice_required?: boolean  // false for mute students — PIN-only auth, no voice passphrase
  // Parent-set cap on total on-screen tutoring minutes before a mandatory eye-rest
  // break is inserted. null/undefined = no cap beyond the normal grade-based
  // block/break cycle in gradeTimer.ts.
  screen_time_limit_minutes?: number | null
  // Length of the mandatory break once screen_time_limit_minutes is reached.
  // Floor of 30 is enforced in gradeTimer.ts regardless of what's stored here.
  eye_rest_break_minutes?: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface VisualAidData {
  id: string
  title: string
  creator: string
  year: string
  wiki_title: string
  description: string
  category: string
}

export interface StreamChunk {
  type: 'text' | 'tool' | 'done' | 'assessment' | 'visual_aid' | 'subject_complete'
  content?: string
  tool?: string
  reason?: 'mastery' | 'frustration'
  data?: { subject: string; total_score: number; adaptive_signal: string }
  visualAid?: VisualAidData
}

export interface SubjectInfo {
  id: Subject
  label: string
  Icon: LucideIcon
  durationMin: number
  color: string
  description: string
}

export const SUBJECTS: SubjectInfo[] = [
  {
    id: 'morning_time',
    label: 'Morning Time',
    Icon: Sun,
    durationMin: 20,
    color: 'bg-amber-50 border-amber-200 text-amber-800',
    description: 'Bible, hymn, poetry & prayer',
  },
  {
    id: 'living_books',
    label: 'Living Books',
    Icon: BookOpen,
    durationMin: 25,
    color: 'bg-emerald-50 border-emerald-200 text-emerald-800',
    description: 'Classical literature & narration',
  },
  {
    id: 'mathematics',
    label: 'Mathematics',
    Icon: Calculator,
    durationMin: 20,
    color: 'bg-blue-50 border-blue-200 text-blue-800',
    description: 'Discovery-based mathematical thinking',
  },
  {
    id: 'nature_study',
    label: 'Nature Study',
    Icon: Leaf,
    durationMin: 20,
    color: 'bg-green-50 border-green-200 text-green-800',
    description: 'Observation, wonder & creation',
  },
  {
    id: 'history',
    label: 'History & Geography',
    Icon: Globe,
    durationMin: 20,
    color: 'bg-orange-50 border-orange-200 text-orange-800',
    description: 'Story-based history & real places',
  },
  {
    id: 'language_arts',
    label: 'Language Arts',
    Icon: PenLine,
    durationMin: 15,
    color: 'bg-purple-50 border-purple-200 text-purple-800',
    description: 'Narration, copywork & grammar',
  },
  {
    id: 'science',
    label: 'Science',
    Icon: FlaskConical,
    durationMin: 20,
    color: 'bg-teal-50 border-teal-200 text-teal-800',
    description: 'Botany, zoology & earth science',
  },
  {
    id: 'art_music',
    label: 'Art & Music',
    Icon: Palette,
    durationMin: 15,
    color: 'bg-rose-50 border-rose-200 text-rose-800',
    description: 'Composer & artist study',
  },
  {
    id: 'saints',
    label: 'Saints & Catechism',
    Icon: Star,
    durationMin: 15,
    color: 'bg-gold-50 border-gold-200 text-gold-700',
    description: 'Saints, catechism & virtue formation',
  },
  {
    id: 'free_study',
    label: 'Free Study',
    Icon: Sparkles,
    durationMin: 20,
    color: 'bg-yellow-50 border-yellow-200 text-yellow-800',
    description: 'Student-directed exploration',
  },
]

export const SUBJECT_MAP: Record<Subject, SubjectInfo> = Object.fromEntries(
  SUBJECTS.map((s) => [s.id, s])
) as Record<Subject, SubjectInfo>

export interface NarrationAssessmentData {
  subject: string
  completeness: number
  sequence: number
  detail: number
  language_quality: number
  synthesis: number
  total_score: number
  concepts_demonstrated: string[]
  misconceptions: string[]
  adaptive_signal: 'advance' | 'repeat' | 'review_prerequisite'
  bede_observation: string
  assessed_at: string
}

export interface LearnerProfileData {
  trivium_stage: 'grammar' | 'logic' | 'rhetoric'
  processing_style: 'visual' | 'auditory' | 'reading_writing' | 'kinesthetic'
  narration_mode: 'sequential' | 'associative'
  attention_profile: 'short_blocks' | 'sustained' | 'variable'
  session_count_assessed: number
  bede_profile_notes: string
  assessed_at: string
}
