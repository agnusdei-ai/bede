import type { ClassicalArtsProgram, ClassicalArtsProgramMatch } from '../services/api'

export type ProgramId = ClassicalArtsProgram['id']
const ids: ProgramId[] = ['bede', 'valor', 'memoria_press', 'other']

export function readClassicalSelection(note?: string | null) {
  const match = /^Bede classical arts: ([a-z][a-z0-9-]{0,63}); week=([1-3]); support=(guided|independent|extension)(?:; program=([a-z_]+)(?:; assignment=([a-f0-9]{24}))?)?$/.exec(note ?? '')
  if (!match || !ids.includes((match[4] ?? 'bede') as ProgramId)) return null
  return {
    unit: match[1], week: Number(match[2]),
    support: match[3] as 'guided' | 'independent' | 'extension',
    program: (match[4] ?? 'bede') as ProgramId, assignment: match[5] ?? '',
  }
}

export default function ClassicalProgramPicker({ program, onChange, metadata, locale }: {
  program: ProgramId; onChange: (id: ProgramId) => void
  metadata?: ClassicalArtsProgram; locale: 'en' | 'es'
}) {
  const es = locale === 'es'
  const names = {
    bede: es ? 'Secuencia clásica de Bede' : 'Bede classical sequence',
    valor: 'Valor Education', memoria_press: 'Memoria Press',
    other: es ? 'Otro currículo / selección adulta' : 'Another curriculum / adult selection',
  }
  return <div className="space-y-2">
    <label className="classical-arts-no-print block text-xs font-semibold">
      {es ? 'Programa curricular' : 'Curriculum program'}
      <select value={program} onChange={(event) => onChange(event.target.value as ProgramId)}
        className="mt-1 block min-h-[44px] w-full rounded-lg border border-navy-200 bg-white px-3 py-2 font-normal">
        {ids.map((id) => <option key={id} value={id}>{names[id]}</option>)}
      </select>
    </label>
    {metadata && <div className="space-y-1 text-xs leading-relaxed text-gray-600">
      <p><strong>{metadata.label}.</strong> {metadata.description}</p>
      <p>{metadata.schedule_note}</p>
      {program !== 'bede' && <p>{metadata.coverage_note}</p>}
      {metadata.references.length > 0 && <details>
        <summary className="cursor-pointer">{es ? 'Referencias del programa' : 'Program references'}</summary>
        <ul className="mt-1 space-y-1">{metadata.references.map((ref) => <li key={ref.url}>
          <a className="underline" href={ref.url} target="_blank" rel="noopener noreferrer">{ref.title}</a>
          <p>{ref.locator}</p>
        </li>)}</ul>
      </details>}
    </div>}
  </div>
}

export function ClassicalProgramMatch({ match, locale }: {
  match?: ClassicalArtsProgramMatch | null; locale: 'en' | 'es'
}) {
  if (!match) return null
  const es = locale === 'es'
  return <div className="space-y-1 border-l-2 border-navy-200 pl-3 text-xs leading-relaxed">
    <p><strong>{match.work}</strong> · {es ? 'Ubicación publicada: grado' : 'Published placement: Grade'} {match.placement}</p>
    {match.reference_isbn && <p>{match.reference_kind === 'study_guide'
      ? (es ? 'ISBN de la guía' : 'Guide ISBN') : (es ? 'ISBN del texto de la lista' : 'Listed text ISBN')}: {match.reference_isbn}</p>}
    <p>{match.edition_note}</p>
    <a className="underline" href={match.reference_url} target="_blank" rel="noopener noreferrer">
      {es ? 'Consultar la referencia del programa' : 'Check the program reference'}
    </a>
  </div>
}
