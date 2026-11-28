import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { BookOpen, Printer, RotateCcw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { classicalArtsImageUrl, ClassicalArtsSourcePendingError, type ClassicalArtsCatalog, type ClassicalArtsLesson } from './api'
import ClassicalProgramPicker, { ClassicalProgramMatch, readClassicalSelection, type ProgramId } from './ClassicalProgramPicker'

function ClassicalArtworkPreview({ url, title, locale }: { url: string | null; title: string; locale: string }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [url])
  return !url || failed ? <p role="status">{locale === 'es' ? 'Imagen no disponible' : 'Image unavailable'}</p>
    : <img src={url} alt={title} loading="lazy" onError={() => setFailed(true)} className="max-h-96 w-full object-contain" />
}

type Support = 'guided' | 'independent' | 'extension'

const copy = {
  en: {
    title: 'Classical literature & arts',
    intro: 'A source-grounded rehearsal for an adult and learner to share. Choose a text, then read and discuss it together.',
    unit: 'Literature or arts unit',
    choose: 'Choose a unit',
    week: 'Bede support week',
    checkAssignment: 'I checked the assigned reading, its edition and this supporting passage.',
    support: 'Instruction style',
    guided: 'Guided',
    independent: 'Independent',
    extension: 'Extension',
    loadingCatalog: 'Loading the classical arts catalog…',
    loadingLesson: 'Preparing this week’s rehearsal…',
    errorCatalog: 'The catalog could not be loaded. Your setup remains unchanged.',
    errorLesson: 'This rehearsal could not be loaded.',
    sourcePending: 'Source verification is still pending. No lesson is available yet.',
    lessonNeeded: 'Load the lesson for this exact unit and selection before using it for tutoring.',
    retryLoad: 'Try again',
    cancel: 'Cancel loading',
    canceled: 'Loading canceled. Nothing was changed.',
    empty: 'There are no classical arts units available for this grade yet.',
    scope: 'Scope',
    content: 'Content note',
    objective: 'Purpose for this week',
    instructions: 'Adult instructions',
    source: 'Cited source',
    sourceText: 'Exact source text',
    sourceLink: 'Open the cited source',
    sourceEnglish: 'English source text',
    assessment: 'Questions for conversation',
    use: 'Use for tutoring',
    useHelp: 'This updates the editable unit note only. It is not saved until you save the parent setup.',
    noSubject: 'Choose a unit whose subject is selected for this learner to use it for tutoring.',
    rehearsal: 'Shared reading rehearsal',
    localOnly: 'Local to this page only. No draft is saved, and no audio is recorded.',
    role: 'Read as',
    cueOnly: 'Cue-only view',
    showLine: 'Reveal my line',
    hideLine: 'Hide my line',
    yourLine: 'Your line',
    cues: 'Other speakers’ cues',
    selfRead: 'Read aloud yourself',
    typed: 'Type a response',
    response: 'A thought to share (optional)',
    responseHint: 'This stays in this page and is not saved.',
    retry: 'Begin this rehearsal again',
    print: 'Print this lesson',
    sourceRights: 'Rights',
    noRehearsal: 'A shared rehearsal is not included for this lesson.',
  },
  es: {
    title: 'Literatura clásica y artes',
    intro: 'Un ensayo basado en fuentes para compartir entre una persona adulta y quien aprende. Elijan un texto y léanlo y conversen juntos.',
    unit: 'Unidad de literatura o artes',
    choose: 'Elegir una unidad',
    week: 'Semana de apoyo de Bede',
    checkAssignment: 'He comprobado la lectura asignada, su edición y este pasaje de apoyo.',
    support: 'Estilo de instrucción',
    guided: 'Con guía',
    independent: 'Independiente',
    extension: 'Ampliación',
    loadingCatalog: 'Cargando el catálogo de artes clásicas…',
    loadingLesson: 'Preparando el ensayo de esta semana…',
    errorCatalog: 'No se pudo cargar el catálogo. La configuración permanece sin cambios.',
    errorLesson: 'No se pudo cargar este ensayo.',
    sourcePending: 'La verificación de la fuente sigue pendiente. Aún no hay una lección disponible.',
    lessonNeeded: 'Carga la lección de esta unidad y selección exactas antes de usarla en la tutoría.',
    retryLoad: 'Intentar de nuevo',
    cancel: 'Cancelar la carga',
    canceled: 'Carga cancelada. No se cambió nada.',
    empty: 'Aún no hay unidades de artes clásicas disponibles para este grado.',
    scope: 'Alcance',
    content: 'Nota sobre el contenido',
    objective: 'Propósito de esta semana',
    instructions: 'Instrucciones para la persona adulta',
    source: 'Fuente citada',
    sourceText: 'Texto exacto de la fuente',
    sourceLink: 'Abrir la fuente citada',
    sourceEnglish: 'Texto fuente en inglés',
    assessment: 'Preguntas para conversar',
    use: 'Usar para la tutoría',
    useHelp: 'Esto actualiza solo la nota editable de la unidad. No se guarda hasta guardar la configuración parental.',
    noSubject: 'Para usarla en la tutoría, elige una unidad cuya materia esté seleccionada para este estudiante.',
    rehearsal: 'Lectura compartida',
    localOnly: 'Solo en esta página. No se guarda ningún borrador ni se graba audio.',
    role: 'Leer como',
    cueOnly: 'Vista de pistas',
    showLine: 'Mostrar mi parlamento',
    hideLine: 'Ocultar mi parlamento',
    yourLine: 'Tu parlamento',
    cues: 'Pistas de las demás voces',
    selfRead: 'Leer en voz alta',
    typed: 'Escribir una respuesta',
    response: 'Una idea para compartir (opcional)',
    responseHint: 'Permanece en esta página y no se guarda.',
    retry: 'Empezar de nuevo',
    print: 'Imprimir esta lección',
    sourceRights: 'Derechos',
    noRehearsal: 'Esta lección no incluye una lectura compartida.',
  },
} as const

export default function ClassicalArtsWorkshop({
  grade,
  subjects,
  currentUnit = '',
  loadList,
  loadLesson,
  onChooseUnit,
}: {
  grade: string
  subjects: string[]
  currentUnit?: string
  loadList: (grade: string, locale: string, program: string) => Promise<ClassicalArtsCatalog>
  loadLesson: (unit: string, grade: string, week: number, locale: string, support: string, program: string) => Promise<ClassicalArtsLesson>
  onChooseUnit: (note: string) => void
}) {
  const { i18n } = useTranslation()
  const locale = i18n.resolvedLanguage?.startsWith('es') || i18n.language.startsWith('es') ? 'es' : 'en'
  const tx = copy[locale]
  const gradeNumber = Number(grade.trim())
  const supportedGrade = Number.isInteger(gradeNumber) && gradeNumber >= 4 && gradeNumber <= 12
  const savedSelection = useMemo(() => readClassicalSelection(currentUnit), [currentUnit])
  const [program, setProgram] = useState<ProgramId>(savedSelection?.program ?? 'bede')
  const [confirmedToken, setConfirmedToken] = useState(savedSelection?.assignment ?? '')
  const catalogKey = `${grade.trim()}|${locale}|${program}`
  const instanceId = useId().replace(/:/g, '')
  const printId = `classical-arts-${instanceId}`
  const printClass = `classical-arts-printing-${instanceId}`
  const [catalog, setCatalog] = useState<ClassicalArtsCatalog | null>(null)
  const [catalogScope, setCatalogScope] = useState('')
  const [catalogError, setCatalogError] = useState(false)
  const [catalogErrorScope, setCatalogErrorScope] = useState('')
  const [catalogPending, setCatalogPending] = useState(false)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [unitId, setUnitId] = useState('')
  const [week, setWeek] = useState(1)
  const [support, setSupport] = useState<Support>('guided')
  const [lesson, setLesson] = useState<ClassicalArtsLesson | null>(null)
  const [lessonScope, setLessonScope] = useState('')
  const [lessonLoading, setLessonLoading] = useState(false)
  const [lessonError, setLessonError] = useState(false)
  const [lessonErrorScope, setLessonErrorScope] = useState('')
  const [lessonPending, setLessonPending] = useState(false)
  const [canceled, setCanceled] = useState(false)
  const [generation, setGeneration] = useState(0)
  const [role, setRole] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [route, setRoute] = useState<'read' | 'type'>('read')
  const [response, setResponse] = useState('')
  const listRequest = useRef(0)
  const lessonRequest = useRef(0)
  const currentCatalog = catalogScope === catalogKey ? catalog : null
  const currentUnits = useMemo(
    () => currentCatalog?.units.filter((item) => item.min_grade <= gradeNumber) ?? [],
    [currentCatalog, gradeNumber],
  )
  const selectedUnit = useMemo(
    () => currentUnits.find((item) => item.id === unitId) ?? null,
    [currentUnits, unitId],
  )
  const lessonKey = `${unitId}|${grade.trim()}|${week}|${locale}|${support}|${program}`
  const currentCatalogError = catalogError && catalogErrorScope === catalogKey
  const currentLessonError = lessonError && lessonErrorScope === lessonKey
  const lessonReady = !!lesson && lessonScope === lessonKey
    && lesson.unit_id === unitId && lesson.week === week
  const assignmentChecked = program === 'bede' || (lessonReady && !!lesson?.selection_token && confirmedToken === lesson.selection_token)
  const canChoose = currentCatalog?.runtime_enabled === true && !!selectedUnit?.subjects.some((subject) => subjects.includes(subject)) && lessonReady && assignmentChecked
  const roles = useMemo(
    () => [...new Set(lesson?.rehearsal.map((line) => line.speaker) ?? [])],
    [lesson],
  )

  useEffect(() => {
    setProgram(savedSelection?.program ?? 'bede')
    setConfirmedToken(savedSelection?.assignment ?? '')
  }, [savedSelection])

  useEffect(() => {
    if (savedSelection?.program === program && currentCatalog
      && currentUnits.some((unit) => unit.id === savedSelection.unit)) {
      setUnitId(savedSelection.unit)
      setWeek(savedSelection.week)
      setSupport(savedSelection.support)
    }
  }, [savedSelection, program, currentCatalog, currentUnits])

  const fetchCatalog = () => {
    const request = ++listRequest.current
    lessonRequest.current += 1
    setCatalog(null)
    setCatalogScope('')
    setLesson(null)
    setLessonScope('')
    setUnitId('')
    setLessonLoading(false)
    setLessonError(false)
    setLessonErrorScope('')
    setLessonPending(false)
    setCatalogLoading(true)
    setCatalogError(false)
    setCatalogErrorScope('')
    setCatalogPending(false)
    setCanceled(false)
    loadList(grade, locale, program).then((data) => {
      if (request !== listRequest.current) return
      if ((data.program?.id ?? 'bede') !== program) throw new Error('Catalog program did not match the request')
      setCatalog(data)
      setCatalogScope(catalogKey)
    }).catch((error: unknown) => {
      if (request === listRequest.current) {
        listRequest.current += 1
        lessonRequest.current += 1
        setCatalog(null)
        setCatalogScope('')
        setLesson(null)
        setLessonScope('')
        setLessonError(false)
        setLessonErrorScope('')
        setLessonPending(false)
        setUnitId('')
        setCatalogPending(error instanceof ClassicalArtsSourcePendingError)
        setCatalogError(true)
        setCatalogErrorScope(catalogKey)
        setCatalogLoading(false)
      }
    }).finally(() => {
      if (request === listRequest.current) setCatalogLoading(false)
    })
  }

  useEffect(() => {
    listRequest.current += 1
    lessonRequest.current += 1
    setCatalog(null)
    setCatalogScope('')
    setLesson(null)
    setLessonScope('')
    setUnitId('')
    setCatalogError(false)
    setCatalogErrorScope('')
    setCatalogPending(false)
    setLessonError(false)
    setLessonErrorScope('')
    setLessonPending(false)
    setCanceled(false)
    if (supportedGrade) fetchCatalog()
    return () => {
      listRequest.current += 1
      lessonRequest.current += 1
    }
    // Catalog loader is a stable imported API function at both call sites.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grade, locale, program, loadList, supportedGrade])

  const cancelLessonLoad = () => {
    lessonRequest.current += 1
    setLessonLoading(false)
    setCanceled(true)
    setLesson(null)
    setLessonScope('')
  }

  useEffect(() => {
    const request = ++lessonRequest.current
    const hasLessonSelection = !!unitId && !!selectedUnit && !!currentCatalog
    setLesson(null)
    setLessonScope('')
    setLessonError(false)
    setLessonErrorScope('')
    setLessonPending(false)
    setCanceled(false)
    if (hasLessonSelection) {
      setLessonLoading(true)
      loadLesson(unitId, grade, week, locale, support, program).then((data) => {
        if (request !== lessonRequest.current) return
        if (data.unit_id !== unitId || data.week !== week) throw new Error('Lesson selection did not match the request')
        if ((data.program?.id ?? 'bede') !== program
          || (program !== 'bede' && !/^[a-f0-9]{24}$/.test(data.selection_token ?? ''))) throw new Error('Lesson program or source binding did not match the request')
        setLesson(data)
        setLessonScope(lessonKey)
        setRole(data.rehearsal[0]?.speaker ?? '')
        setRevealed(false)
        setResponse('')
      }).catch((error: unknown) => {
        if (request === lessonRequest.current) {
          setLesson(null)
          setLessonScope('')
          setLessonPending(error instanceof ClassicalArtsSourcePendingError)
          setLessonError(true)
          setLessonErrorScope(lessonKey)
        }
      }).finally(() => {
        if (request === lessonRequest.current) setLessonLoading(false)
      })
    } else {
      setLessonLoading(false)
    }
    return () => {
      if (lessonRequest.current === request) lessonRequest.current += 1
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unitId, week, support, grade, locale, program, loadLesson, generation, currentCatalog, selectedUnit])

  useEffect(() => () => {
    lessonRequest.current += 1
    listRequest.current += 1
    document.body.classList.remove(printClass)
  }, [])

  const applyUnit = () => {
    if (selectedUnit && canChoose && lessonReady) {
      if (program !== 'bede' && !lesson?.selection_token) return
      const alignment = program === 'bede' ? '' : `; program=${program}; assignment=${lesson?.selection_token}`
      onChooseUnit(`Bede classical arts: ${selectedUnit.id}; week=${week}; support=${support}${alignment}`)
    }
  }
  const selectedRole = lesson?.rehearsal.filter((line) => line.speaker === role) ?? []
  const cues = lesson?.rehearsal.filter((line) => line.speaker !== role) ?? []

  if (!supportedGrade) return null

  return (
    <section id={printId} className="classical-arts-workshop space-y-4 rounded-xl border border-sage-200 bg-parchment-50 p-4 text-sm text-navy-800" aria-labelledby={`${printId}-title`}>
      <style>{`
        @media print {
          body.${printClass} * { visibility: hidden !important; }
          body.${printClass} #${printId}, body.${printClass} #${printId} * { visibility: visible !important; }
          body.${printClass} #${printId} { position: absolute; inset: 0; width: 100%; border: 0; background: white; color: black; }
          body.${printClass} #${printId} .classical-arts-no-print { display: none !important; }
          body.${printClass} #${printId} .classical-arts-source { break-inside: avoid; }
        }
      `}</style>
      <div className="flex items-start gap-3">
        <BookOpen size={19} className="mt-0.5 shrink-0 text-navy-600" />
        <div>
          <h3 id={`${printId}-title`} className="font-display text-base font-bold">{tx.title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-gray-600">{tx.intro}</p>
        </div>
      </div>

      <ClassicalProgramPicker program={program} onChange={setProgram} metadata={currentCatalog?.program} locale={locale} />
      {catalogLoading ? <div role="status" className="rounded-lg bg-white p-3 text-xs text-gray-600">{tx.loadingCatalog}</div> : null}
      {currentCatalogError ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
        <p>{catalogPending ? tx.sourcePending : tx.errorCatalog}</p><button type="button" className="mt-2 underline" onClick={fetchCatalog}>{tx.retryLoad}</button>
      </div> : null}
      {catalogLoading && <button type="button" className="classical-arts-no-print text-xs underline" onClick={() => {
        listRequest.current += 1
        setCatalogLoading(false)
        setCanceled(true)
      }}>{tx.cancel}</button>}
      {canceled && <p role="status" className="text-xs text-gray-600">{tx.canceled}</p>}
      {!catalogLoading && !catalogError && currentCatalog && currentUnits.length === 0 && (
        <p role="status" className="rounded-lg bg-white p-3 text-xs text-gray-600">{tx.empty}</p>
      )}
      {currentCatalog?.scope_note && <p className="text-xs leading-relaxed text-gray-600"><strong>{tx.scope}:</strong> {currentCatalog.scope_note}</p>}
      {currentCatalog && !currentCatalog.runtime_enabled && <p role="status" className="text-xs leading-relaxed text-amber-800">{locale === 'es' ? 'Vista de revisión. La tutoría con estas unidades todavía no está activada.' : 'Review preview. Tutoring with these units has not been activated.'}</p>}

      {currentCatalog && currentUnits.length > 0 && (
        <div className="classical-arts-no-print grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold">{tx.unit}
            <select className="mt-1 block min-h-[44px] w-full rounded-lg border border-sage-300 bg-white px-3 py-2 font-normal" value={unitId} onChange={(event) => {
              setUnitId(event.target.value)
              setWeek(1)
            }}>
              <option value="">{tx.choose}</option>
              {currentUnits.map((unit) => <option key={unit.id} value={unit.id}>{unit.title}</option>)}
            </select>
          </label>
          {selectedUnit && <>
            <label className="text-xs font-semibold">{tx.week}
              <select className="mt-1 block min-h-[44px] w-full rounded-lg border border-sage-300 bg-white px-3 py-2 font-normal" value={week} onChange={(event) => setWeek(Number(event.target.value))}>
                {Array.from({ length: selectedUnit.weeks }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}
              </select>
            </label>
            <label className="text-xs font-semibold sm:col-span-2">{tx.support}
              <select className="mt-1 block min-h-[44px] w-full rounded-lg border border-sage-300 bg-white px-3 py-2 font-normal" value={support} onChange={(event) => setSupport(event.target.value as Support)}>
                {(['guided', 'independent', 'extension'] as const).map((value) => <option key={value} value={value}>{tx[value]}</option>)}
              </select>
            </label>
          </>}
        </div>
      )}

      {selectedUnit && <div className="space-y-2 rounded-lg border border-sage-200 bg-white p-3">
        <p className="font-semibold">{selectedUnit.title}</p>
        <p className="text-xs leading-relaxed text-gray-600">{selectedUnit.summary}</p>
        {selectedUnit.content_note && <p className="text-xs leading-relaxed text-gray-600"><strong>{tx.content}:</strong> {selectedUnit.content_note}</p>}
        <ClassicalProgramMatch match={selectedUnit.program_match} locale={locale} />
        {program !== 'bede' && lessonReady && lesson && <label className="classical-arts-no-print flex items-start gap-2 py-2 text-xs leading-relaxed">
          <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0" checked={assignmentChecked}
            onChange={(event) => setConfirmedToken(event.target.checked ? lesson.selection_token ?? '' : '')} />
          {tx.checkAssignment}
        </label>}
        <button type="button" onClick={applyUnit} disabled={!canChoose} className="classical-arts-no-print min-h-[42px] rounded-lg bg-navy-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{tx.use}</button>
        <p className="text-[0.7rem] leading-relaxed text-gray-500">{!selectedUnit.subjects.some((subject) => subjects.includes(subject)) ? tx.noSubject : !assignmentChecked && lessonReady ? tx.checkAssignment : lessonReady ? tx.useHelp : tx.lessonNeeded}</p>
      </div>}

      {lessonLoading && <div role="status" className="rounded-lg bg-white p-3 text-xs text-gray-600">{tx.loadingLesson}</div>}
      {lessonLoading && <button type="button" className="classical-arts-no-print text-xs underline" onClick={cancelLessonLoad}>{tx.cancel}</button>}
      {currentLessonError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
        <p>{lessonPending ? tx.sourcePending : tx.errorLesson}</p><button type="button" className="mt-2 underline" onClick={() => setGeneration((value) => value + 1)}>{tx.retryLoad}</button>
      </div>}
      {lessonReady && lesson && (
        <article className="space-y-4 border-t border-sage-200 pt-4">
          <header>
            <h4 className="font-display text-lg font-bold">{lesson.title}</h4>
            <p className="mt-1 text-xs leading-relaxed"><strong>{tx.objective}:</strong> {lesson.objective}</p>
          </header>
          <section>
            <h5 className="font-semibold">{tx.instructions}</h5>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-xs leading-relaxed">
              {lesson.steps.map((step, index) => <li key={`${step.label}-${index}`}><strong>{step.label}.</strong> {step.instruction}</li>)}
            </ol>
          </section>
          <section className="classical-arts-source rounded-lg border border-sage-200 bg-white p-3">
            <h5 className="font-semibold">{tx.source}: {lesson.source.title}</h5>
            <p className="text-xs text-gray-600">{lesson.source.locator} · {lesson.source.language}{locale === 'es' && lesson.source.language.toLowerCase().startsWith('en') ? ` — ${tx.sourceEnglish}` : ''}</p>
            <h6 className="mt-3 text-xs font-semibold">{tx.sourceText}{locale === 'es' && lesson.source.language.toLowerCase().startsWith('en') ? ` (${tx.sourceEnglish})` : ''}</h6>
            <blockquote className="mt-1 whitespace-pre-wrap border-l-2 border-sage-400 pl-3 font-serif text-sm leading-relaxed">{lesson.source.text}</blockquote>
            <a className="mt-3 inline-block text-xs font-medium underline" href={lesson.source.url} target="_blank" rel="noopener noreferrer">{tx.sourceLink}</a>
            <p className="mt-1 text-[0.7rem] text-gray-500">{tx.sourceRights}: {lesson.source.rights}</p>
            {lesson.visual_previews.length > 0 && <details className="classical-arts-no-print mt-4">
              <summary className="cursor-pointer text-sm font-semibold">{locale === 'es' ? 'Revisar las cinco imágenes · contienen desnudos artísticos decorativos' : 'Preview the five images · includes decorative artistic nudity'}</summary>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">{lesson.visual_previews.map((image) => <figure key={image.id}>
                <ClassicalArtworkPreview url={classicalArtsImageUrl(image.image_url)} title={locale === 'es' ? image.title_es : image.title} locale={locale} />
                <figcaption className="mt-1 text-xs"><a href={image.source_url} target="_blank" rel="noopener noreferrer" className="underline">{locale === 'es' ? image.title_es : image.title}</a></figcaption>
              </figure>)}</div>
            </details>}
            {lesson.companion_sources.map((source) => <div key={source.id} className="mt-4 border-t border-navy-100 pt-3">
              <h6 className="text-xs font-semibold">{source.title}{locale === 'es' && source.language === 'en' ? ` (${tx.sourceEnglish})` : ''}</h6>
              <p className="text-xs">{source.locator}</p>
              <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-navy-300 pl-3 font-serif text-sm leading-relaxed">{source.text}</blockquote>
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-xs underline">{tx.sourceLink}</a>
            </div>)}
          </section>
          {lesson.assessments.length > 0 && <section>
            <h5 className="font-semibold">{tx.assessment}</h5>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed">{lesson.assessments.map((item, index) => <li key={`${item.kind}-${index}`}>{item.prompt}</li>)}</ul>
          </section>}

          <section className="rounded-lg border border-sage-200 bg-white p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div><h5 className="font-semibold">{tx.rehearsal}</h5><p className="mt-1 text-[0.7rem] text-gray-600">{tx.localOnly}</p></div>
              <button type="button" className="classical-arts-no-print inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-sage-300 px-3 text-xs" onClick={() => {
                document.body.classList.add(printClass)
                const finishPrint = () => document.body.classList.remove(printClass)
                window.addEventListener('afterprint', finishPrint, { once: true })
                try {
                  window.print()
                } catch {
                  window.removeEventListener('afterprint', finishPrint)
                  finishPrint()
                }
              }}><Printer size={14} />{tx.print}</button>
            </div>
            {lesson.rehearsal.length === 0 ? <p className="mt-3 text-xs text-gray-600">{tx.noRehearsal}</p> : <>
              <div className="classical-arts-no-print mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <label className="text-xs font-semibold">{tx.role}
                  <select className="mt-1 block min-h-[44px] w-full rounded-lg border border-sage-300 bg-white px-3 py-2 font-normal" value={role} onChange={(event) => {
                    setRole(event.target.value)
                    setRevealed(false)
                  }}>
                    {roles.map((speaker) => <option key={speaker} value={speaker}>{speaker}</option>)}
                  </select>
                </label>
                <label className="flex min-h-[44px] items-center gap-2 self-end text-xs">
                  <input type="checkbox" checked={!revealed} onChange={(event) => setRevealed(!event.target.checked)} />
                  {tx.cueOnly}
                </label>
              </div>
              {selectedRole.length > 0 && <div className="mt-3 rounded-lg bg-parchment-50 p-3">
                <p className="text-xs font-semibold">{tx.yourLine} — {selectedRole[0].speaker}</p>
                {revealed ? selectedRole.map((line, index) => <p key={`${line.speaker}-${index}`} className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{line.text}</p>) : <p className="mt-1 text-xs italic text-gray-600">{tx.cueOnly}</p>}
                <button type="button" className="classical-arts-no-print mt-2 min-h-[40px] text-xs font-medium underline" onClick={() => setRevealed((value) => !value)}>{revealed ? tx.hideLine : tx.showLine}</button>
              </div>}
              {cues.length > 0 && <div className="mt-3 space-y-2">
                <p className="text-xs font-semibold">{tx.cues}</p>
                {cues.map((cue, index) => <div key={`${cue.speaker}-${index}`} className="rounded-lg bg-parchment-50 p-3">
                  <p className="text-xs font-semibold">{cue.speaker}</p><p className="mt-1 text-xs leading-relaxed">{cue.text}</p>
                </div>)}
              </div>}
              <div className="classical-arts-no-print mt-3 border-t border-sage-100 pt-3">
                <div className="flex flex-wrap gap-2">
                  <button type="button" aria-pressed={route === 'read'} className={`min-h-[40px] rounded-lg px-3 text-xs ${route === 'read' ? 'bg-navy-600 text-white' : 'border border-sage-300'}`} onClick={() => setRoute('read')}>{tx.selfRead}</button>
                  <button type="button" aria-pressed={route === 'type'} className={`min-h-[40px] rounded-lg px-3 text-xs ${route === 'type' ? 'bg-navy-600 text-white' : 'border border-sage-300'}`} onClick={() => setRoute('type')}>{tx.typed}</button>
                </div>
                {route === 'type' && <label className="mt-3 block text-xs font-semibold">{tx.response}
                  <textarea value={response} onChange={(event) => setResponse(event.target.value)} rows={3} className="mt-1 block w-full rounded-lg border border-sage-300 p-2 font-normal" />
                  <span className="mt-1 block font-normal text-gray-500">{tx.responseHint}</span>
                </label>}
                <button type="button" className="mt-3 inline-flex min-h-[40px] items-center gap-1.5 text-xs font-medium underline" onClick={() => {
                  setRevealed(false)
                  setResponse('')
                  setRoute('read')
                  setGeneration((value) => value + 1)
                }}><RotateCcw size={14} />{tx.retry}</button>
              </div>
            </>}
          </section>
        </article>
      )}
    </section>
  )
}
