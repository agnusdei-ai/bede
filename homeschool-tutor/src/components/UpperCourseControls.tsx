import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

export const UPPER_GRADES = ['9', '10', '11', '12']
export type UpperSelection = {
  release_id?: 'bede-upper-2026-reviewed'
  week: number
  lesson_id?: string | null
}
export type UpperRelease = {
  runtime_enabled: boolean
  lessons: Array<{ id: string; title: string; subject: string }>
}

export default function UpperCourseControls({ grade, value, subjects, onChange, load }: {
  grade: string
  value?: UpperSelection | null
  subjects: string[]
  onChange: (value: UpperSelection | null) => void
  load: (grade: string, week: number) => Promise<UpperRelease>
}) {
  const { i18n } = useTranslation()
  const es = i18n.language.startsWith('es')
  const g = grade.trim()
  const upper = UPPER_GRADES.includes(g)
  const [release, setRelease] = useState<UpperRelease | null>(null)
  const [error, setError] = useState(false)
  const week = value?.week ?? 1
  const subjectLabels: Record<string, string> = es ? {
    living_books: 'Literatura', language_arts: 'Composición', history: 'Historia',
    mathematics: 'Matemáticas', science: 'Ciencias', latin: 'Latín', spanish: 'Español',
    logic: 'Lógica y retórica', computing: 'Informática', art_music: 'Bellas artes',
    nature_study: 'Artes prácticas y naturaleza', movement_health: 'Movimiento y salud',
  } : {
    living_books: 'Literature', language_arts: 'Composition', history: 'History',
    mathematics: 'Math', science: 'Science', latin: 'Latin', spanish: 'Spanish',
    logic: 'Logic and rhetoric', computing: 'Computing', art_music: 'Fine arts',
    nature_study: 'Practical arts and nature', movement_health: 'Movement and health',
  }
  const lessonSubjects = [...new Set((release?.lessons ?? []).map(lesson => lesson.subject))]
  useEffect(() => {
    let active = true
    setRelease(null)
    setError(false)
    if (upper) load(g, week).then(data => {
      if (!Array.isArray(data.lessons) || typeof data.runtime_enabled !== 'boolean') throw new Error('Invalid release')
      if (active) setRelease(data)
    }).catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [g, upper, week, load])
  useEffect(() => {
    const lesson = release?.lessons.find(row => row.id === value?.lesson_id)
    if (value && lesson && !subjects.includes(lesson.subject)) onChange({ ...value, lesson_id: null })
  }, [release, value, subjects, onChange])
  if (!upper) return null
  return <fieldset className="space-y-3 rounded-xl border border-sage-200 p-4 text-sm">
    <legend className="px-1 font-semibold">{es ? `Currículo de ${g}.º grado` : `Grade ${g} curriculum`}</legend>
    {error ? <p role="alert">{es ? 'No se pudo cargar el currículo. Tu selección se conserva.' : 'Could not load the curriculum. Your selection is preserved.'}</p>
      : !release ? <p role="status">{es ? 'Cargando…' : 'Loading…'}</p>
      : !release.runtime_enabled ? <p>{es ? 'Este año completo aún no está activo.' : 'This complete year is not active yet.'}</p> : null}
    <label className="flex items-start gap-2">
      <input type="checkbox" checked={!!value} disabled={!release?.runtime_enabled && !value}
        onChange={e => onChange(e.target.checked ? { release_id: 'bede-upper-2026-reviewed', week, lesson_id: null } : null)} />
      <span>{es ? 'Usar el año de Bede seleccionado por el adulto' : 'Use the adult-selected Bede year'}</span>
    </label>
    {value && <div className="space-y-3">
      <label className="block">{es ? 'Semana' : 'Week'}
        <select className="block w-full rounded-lg border p-2" aria-label={es ? 'Semana del currículo' : 'Curriculum week'}
          value={week} disabled={!release?.runtime_enabled}
          onChange={e => onChange({ ...value, week: Number(e.target.value), lesson_id: null })}>
          {Array.from({ length: 36 }, (_, n) => <option key={n + 1} value={n + 1}>{n + 1}</option>)}
        </select>
      </label>
      <label className="block">{es ? 'Lección específica' : 'Specific lesson'}
        <select className="block w-full rounded-lg border p-2" aria-label={es ? 'Lección específica' : 'Specific curriculum lesson'}
          value={value.lesson_id ?? ''} disabled={!release?.runtime_enabled}
          onChange={e => onChange({ ...value, lesson_id: e.target.value || null })}>
          <option value="">{es ? 'Lección de la semana en cada materia seleccionada' : "This week's lesson in each selected subject"}</option>
          {lessonSubjects.map(subject => <optgroup key={subject} label={subjectLabels[subject] ?? subject}
            disabled={!subjects.includes(subject)}>
            {(release?.lessons ?? []).filter(lesson => lesson.subject === subject).map(lesson =>
              <option key={lesson.id} value={lesson.id}
                disabled={!subjects.includes(subject)}>{lesson.title}</option>)}
          </optgroup>)}
        </select>
      </label>
      <p>{es ? 'Elige primero la materia de la lección. La semana no indica dominio ni avance automático.' : 'Enable the lesson’s subject first. The week does not imply mastery or automatic advancement.'}</p>
      <p>{es ? 'Revisado por pasos separados de IA; no es una aceptación humana ni evidencia de eficacia.' : 'Reviewed by separate AI passes; not human acceptance or evidence of effectiveness.'}</p>
      <p>{es ? 'Desactivar este año también quita sus materias de español, informática y movimiento del plan.' : 'Turning off this year also removes its Spanish, computing and movement subjects from the plan.'}</p>
    </div>}
  </fieldset>
}
