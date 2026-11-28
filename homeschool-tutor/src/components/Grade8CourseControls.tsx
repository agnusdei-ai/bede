import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

export type Grade8Selection = {
  release_id?: 'bede-grade8-2026-accepted'
  week: number
  pathway: 'foundations' | 'algebra'
  lesson_id?: string | null
}
export type Grade8Release = {
  runtime_enabled: boolean
  atlas_url?: string
  visual_source_url?: string
  lessons: Array<{ id: string; title: string; subject: string }>
}

export default function Grade8CourseControls({ grade, value, subjects, onChange, load }: {
  grade: string
  value?: Grade8Selection | null
  subjects: string[]
  onChange: (value: Grade8Selection | null) => void
  load: (week: number, pathway: string) => Promise<Grade8Release>
}) {
  const { i18n } = useTranslation()
  const es = i18n.language.startsWith('es')
  const [release, setRelease] = useState<Grade8Release | null>(null)
  const [error, setError] = useState(false)
  const week = value?.week ?? 1
  const pathway = value?.pathway ?? 'foundations'
  const subjectLabels: Record<string, string> = es ? {
    mathematics: 'Matemáticas', living_books: 'Literatura clásica y lectura',
    language_arts: 'Escritura y composición', history: 'Historia y geografía',
    art_music: 'Arte y música', science: 'Ciencias', spanish: 'Español',
    computing: 'Informática e investigación', nature_study: 'Naturaleza y trabajo práctico',
    movement_health: 'Movimiento y salud',
  } : {
    mathematics: 'Math', living_books: 'Classical literature and reading',
    language_arts: 'Writing and composition', history: 'History and geography',
    art_music: 'Art and music', science: 'Science', spanish: 'Spanish',
    computing: 'Computing and research', nature_study: 'Nature and practical work',
    movement_health: 'Movement and health',
  }
  const lessonSubjects = [...new Set((release?.lessons ?? []).map(lesson => lesson.subject))]
  useEffect(() => {
    let active = true
    setRelease(null)
    setError(false)
    if (grade.trim() === '8') load(week, pathway).then(data => {
      if (!Array.isArray(data.lessons) || typeof data.runtime_enabled !== 'boolean') throw new Error('Invalid release')
      if (active) setRelease(data)
    }).catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [grade, week, pathway, load])
  useEffect(() => {
    const lesson = release?.lessons.find(row => row.id === value?.lesson_id)
    if (value && lesson && !subjects.includes(lesson.subject)) onChange({ ...value, lesson_id: null })
  }, [release, value, subjects, onChange])
  if (grade.trim() !== '8') return null
  return <fieldset className="space-y-3 rounded-xl border border-sage-200 p-4 text-sm">
    <legend className="px-1 font-semibold">{es ? 'Currículo de 8.º grado' : 'Grade 8 curriculum'}</legend>
    {release && <p className="flex flex-wrap gap-4">
      {release.atlas_url && <a className="underline" href={release.atlas_url} target="_blank" rel="noopener noreferrer">{es ? 'Atlas del año' : 'Year atlas'}</a>}
      {release.visual_source_url && <a className="underline" href={release.visual_source_url} target="_blank" rel="noopener noreferrer">{es ? 'Fuente visual y guía de lectura' : 'Visual source and reading guide'}</a>}
    </p>}
    {error ? <p role="alert">{es ? 'No se pudo cargar el currículo. Tu selección se conserva.' : 'Could not load the curriculum. Your selection is preserved.'}</p>
      : !release ? <p role="status">{es ? 'Cargando…' : 'Loading…'}</p>
      : !release.runtime_enabled ? <p>{es ? 'Este currículo completo de 8.º grado aún no está activo.' : 'This complete Grade 8 year is not active yet.'}</p> : null}
    <label className="flex items-start gap-2">
      <input type="checkbox" checked={!!value} disabled={!release?.runtime_enabled && !value}
        onChange={e => onChange(e.target.checked ? { release_id: 'bede-grade8-2026-accepted', week, pathway, lesson_id: null } : null)} />
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
      <label className="block">{es ? 'Matemáticas' : 'Math'}
        <select className="block w-full rounded-lg border p-2" aria-label={es ? 'Matemáticas' : 'Math'}
          value={pathway} disabled={!release?.runtime_enabled}
          onChange={e => onChange({ ...value, pathway: e.target.value as Grade8Selection['pathway'], lesson_id: null })}>
          <option value="foundations">{es ? 'Fundamentos matemáticos' : 'Foundations'}</option>
          <option value="algebra">{es ? 'Álgebra I' : 'Algebra I'}</option>
        </select>
      </label>
      <p>{es ? 'Fundamentos y Álgebra I son opciones de matemáticas. Las demás materias se eligen abajo.' : 'Foundations and Algebra I are Math options. Choose the other curriculum subjects below.'}</p>
      <label className="block">{es ? 'Lección específica' : 'Specific lesson'}
        <select className="block w-full rounded-lg border p-2" aria-label={es ? 'Lección específica' : 'Specific curriculum lesson'}
          value={value.lesson_id ?? ''} disabled={!release?.runtime_enabled}
          onChange={e => onChange({ ...value, lesson_id: e.target.value || null })}>
          <option value="">{es ? 'Inicio de cada materia seleccionada' : 'Start of each selected subject'}</option>
          {lessonSubjects.map(subject => <optgroup key={subject} label={subjectLabels[subject] ?? subject}
            disabled={!subjects.includes(subject)}>
            {(release?.lessons ?? []).filter(lesson => lesson.subject === subject).map(lesson =>
              <option key={lesson.id} value={lesson.id}
                disabled={!subjects.includes(subject)}>{lesson.title}</option>)}
          </optgroup>)}
        </select>
      </label>
      <p>{es ? 'Elige primero la materia de la lección. La semana y la ruta no indican dominio ni avance automático.' : 'Enable the lesson’s subject first. Week and pathway do not imply mastery or automatic advancement.'}</p>
      <p>{es ? 'Elige las materias de esta sesión y distribuye las demás a lo largo de la semana.' : 'Choose subjects for this session and rotate the others across the week.'}</p>
      <p>{es ? 'Desactivar este año también quita sus materias de español, informática y movimiento del plan.' : 'Turning off this year also removes its Spanish, computing and movement subjects from the plan.'}</p>
    </div>}
  </fieldset>
}
