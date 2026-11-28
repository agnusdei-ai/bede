import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

type GradeRelease = {
  grade: string
  default_route: 'catalog_guided' | 'grade_specific_practice'
  accepted_full_year: { release_id: string; runtime_enabled: boolean } | null
  reviewed_full_year?: { release_id: string; runtime_enabled: boolean } | null
}
type Availability = { contract_version: number; grades: GradeRelease[] }

export default function CurriculumAvailability({ grade, load }: {
  grade: string
  load: () => Promise<Availability>
}) {
  const { i18n } = useTranslation()
  const es = i18n.language.startsWith('es')
  const [data, setData] = useState<Availability | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let active = true
    let request = 0
    const refresh = () => {
      const current = ++request
      load().then(value => {
        if (value.contract_version !== 1 || !Array.isArray(value.grades)
          || value.grades.some(row => typeof row.grade !== 'string'
            || !['catalog_guided', 'grade_specific_practice'].includes(row.default_route)
            || (row.accepted_full_year !== null
              && (typeof row.accepted_full_year?.runtime_enabled !== 'boolean'
                || typeof row.accepted_full_year?.release_id !== 'string'))
            || (row.reviewed_full_year != null
              && (typeof row.reviewed_full_year.runtime_enabled !== 'boolean'
                || typeof row.reviewed_full_year.release_id !== 'string')))) {
          throw new Error('Invalid curriculum availability')
        }
        if (active && current === request) { setData(value); setError(false) }
      }).catch(() => {
        if (active && current === request) { setData(null); setError(true) }
      })
    }
    refresh()
    window.addEventListener('focus', refresh)
    const timer = window.setInterval(refresh, 60_000)
    return () => { active = false; window.removeEventListener('focus', refresh); window.clearInterval(timer) }
  }, [load])
  const row = data?.grades.find(value => value.grade === grade.trim().toUpperCase())
  const text = error || (data && !row)
    ? (es ? 'No se pudo verificar el currículo.' : 'Curriculum availability could not be verified.')
    : !row ? (es ? 'Verificando currículo…' : 'Checking curriculum…')
      : row.accepted_full_year
        ? row.accepted_full_year.runtime_enabled
          ? (es ? 'Año completo aceptado disponible; selección a cargo del adulto.' : 'Accepted full year available; adult selection required.')
          : (es ? 'Año completo aceptado; no está activo en este entorno.' : 'Accepted full year; not active in this runtime.')
        : row.reviewed_full_year
          ? row.reviewed_full_year.runtime_enabled
            ? (es ? 'Año completo revisado disponible; selección a cargo del adulto.' : 'Reviewed full year available; adult selection required.')
            : (es ? 'Año completo revisado; no está activo en este entorno.' : 'Reviewed full year; not active in this runtime.')
        : row.default_route === 'catalog_guided'
          ? (es ? 'Orientación basada en el catálogo; no es una versión completa del año.' : 'Catalog-guided instruction; not a complete authored-year release.')
          : (es ? 'Práctica por grado; el año completo aún no está publicado.' : 'Grade-specific practice; the full year is not published yet.')
  return <p className="text-sm" role="status">{text}</p>
}
