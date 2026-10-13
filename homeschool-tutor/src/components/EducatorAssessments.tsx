import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ClipboardList, Plus, Trash2 } from 'lucide-react'
import {
  fetchEducatorAssessments, removeEducatorAssessment, saveEducatorAssessment,
} from '../services/api'
import type {
  EducatorAssessmentAssistance, EducatorAssessmentBand,
  EducatorAssessmentFramework, EducatorAssessmentRecord,
  EducatorAssessmentScoreUnit,
} from '../services/api'

// These labels mirror the backend allowlist. They describe the external
// educator's REPORT, never administer DIBELS or infer published cut scores.
const DIBELS_MEASURES = [
  'LNF', 'PSF', 'NWF_CLS', 'NWF_WRC', 'WRF',
  'ORF_WC', 'ORF_ACCURACY', 'MAZE', 'COMPOSITE',
] as const
const CLASSICAL_MEASURES = [
  'oral_narration', 'oral_examination', 'composition', 'translation',
  'observation', 'applied_work',
] as const
const UNITS: EducatorAssessmentScoreUnit[] = [
  'count', 'correct_per_minute', 'percent', 'points', 'other',
]
const BANDS: EducatorAssessmentBand[] = [
  'not_reported', 'at_or_above_benchmark', 'below_benchmark',
  'well_below_benchmark',
]
const ASSISTANCE: EducatorAssessmentAssistance[] = [
  'unaided', 'with_a_hint', 'with_help',
]

function todayLocal() {
  const d = new Date()
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

export default function EducatorAssessments({
  token, studentName,
}: {
  token: string
  studentName: string
}) {
  const { t } = useTranslation()
  const [records, setRecords] = useState<EducatorAssessmentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [framework, setFramework] = useState<EducatorAssessmentFramework>('dibels8')
  const [measure, setMeasure] = useState('ORF_WC')
  const [assessedOn, setAssessedOn] = useState(todayLocal)
  const [sourceName, setSourceName] = useState('')
  const [score, setScore] = useState('')
  const [scoreUnit, setScoreUnit] = useState<EducatorAssessmentScoreUnit>('correct_per_minute')
  const [band, setBand] = useState<EducatorAssessmentBand>('not_reported')
  const [assistance, setAssistance] = useState<EducatorAssessmentAssistance>('unaided')

  useEffect(() => {
    let active = true
    setLoading(true)
    setRecords([])
    setMessage('')
    fetchEducatorAssessments(token, studentName)
      .then((rows) => { if (active) setRecords(rows) })
      .catch(() => { if (active) setMessage(t('assessmentStudio.loadError')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, studentName, t])

  const changeFramework = (next: EducatorAssessmentFramework) => {
    setFramework(next)
    setMeasure(next === 'dibels8' ? 'ORF_WC' : next === 'classical' ? 'oral_narration' : '')
    setScore('')
    setBand('not_reported')
  }

  const save = async () => {
    if (saving || !sourceName.trim() || !measure.trim() ||
        (framework !== 'classical' && (!score.trim() || !Number.isFinite(Number(score))))) {
      setMessage(t('assessmentStudio.requiredError'))
      return
    }
    setSaving(true)
    setMessage('')
    try {
      const result = await saveEducatorAssessment(token, studentName, {
        framework,
        measure: measure.trim(),
        assessed_on: assessedOn,
        source_name: sourceName.trim(),
        ...(framework === 'classical'
          ? { assistance }
          : {
            score: Number(score),
            score_unit: scoreUnit,
            ...(framework === 'dibels8' ? { reported_band: band } : {}),
          }),
      })
      setRecords((prev) => [result, ...prev])
      setExpanded(false)
      setScore('')
      setSourceName('')
    } catch {
      setMessage(t('assessmentStudio.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: number) => {
    if (!window.confirm(t('assessmentStudio.confirmRemove'))) return
    setMessage('')
    try {
      await removeEducatorAssessment(token, studentName, id)
      setRecords((prev) => prev.filter((entry) => entry.id !== id))
    } catch {
      setMessage(t('assessmentStudio.removeError'))
    }
  }

  const inputStyle = 'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800'
  const readableMeasure = (record: EducatorAssessmentRecord) =>
    record.framework === 'classical'
      ? t('assessmentStudio.measure_' + record.measure, { defaultValue: record.measure })
      : record.framework === 'dibels8'
        ? t('assessmentStudio.measure_' + record.measure, { defaultValue: record.measure })
        : record.measure

  return (
    <section className="rounded-2xl border border-sage-100 bg-white p-4 sm:p-5 shadow-sm" aria-label={t('assessmentStudio.title')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <ClipboardList size={19} className="mt-0.5 shrink-0 text-sage-700" />
          <div>
            <h2 className="font-display text-base font-semibold text-gray-800">
              {t('assessmentStudio.title')}
            </h2>
            <p className="text-xs text-gray-500 mt-1">{t('assessmentStudio.description')}</p>
          </div>
        </div>
        <button type="button" onClick={() => { setExpanded(!expanded); setMessage('') }}
          aria-expanded={expanded}
          className="inline-flex items-center gap-1.5 rounded-lg bg-navy-50 px-3 py-2 text-sm font-medium text-navy-800">
          <Plus size={15} /> {t('assessmentStudio.add')}
        </button>
      </div>
      <p className="mt-3 text-xs text-gray-500">{t('assessmentStudio.boundary')}</p>

      {expanded && (
        <form className="mt-4 space-y-3 rounded-xl border border-sage-100 bg-parchment-50 p-3 sm:p-4"
          onSubmit={(event) => { event.preventDefault(); void save() }}>
          <div>
            <label htmlFor="assessment-framework" className="label">{t('assessmentStudio.framework')}</label>
            <select id="assessment-framework" className={inputStyle} value={framework}
              onChange={(e) => changeFramework(e.target.value as EducatorAssessmentFramework)}>
              <option value="dibels8">{t('assessmentStudio.dibels8')}</option>
              <option value="classical">{t('assessmentStudio.classical')}</option>
              <option value="external_other">{t('assessmentStudio.externalOther')}</option>
            </select>
          </div>
          {framework === 'dibels8' && (
            <p className="text-xs text-gray-600">{t('assessmentStudio.dibelsDisclaimer')}
              {' '}<a href="https://dibels.uoregon.edu/materials/dibels" target="_blank" rel="noopener noreferrer"
                className="underline text-navy-700">{t('assessmentStudio.officialGuide')}</a>
            </p>
          )}
          <div>
            <label htmlFor="assessment-measure" className="label">{t('assessmentStudio.measure')}</label>
            {framework === 'external_other'
              ? <input id="assessment-measure" required maxLength={85} className={inputStyle}
                  value={measure} onChange={(e) => setMeasure(e.target.value)} />
              : <select id="assessment-measure" className={inputStyle} value={measure}
                  onChange={(e) => setMeasure(e.target.value)}>
                  {(framework === 'dibels8' ? DIBELS_MEASURES : CLASSICAL_MEASURES).map((key) => (
                    <option key={key} value={key}>
                      {t('assessmentStudio.measure_' + key)}
                    </option>
                  ))}
                </select>
            }
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="assessment-date" className="label">{t('assessmentStudio.date')}</label>
              <input id="assessment-date" type="date" required max={todayLocal()}
                className={inputStyle} value={assessedOn} onChange={(e) => setAssessedOn(e.target.value)} />
            </div>
            <div>
              <label htmlFor="assessment-source" className="label">{t('assessmentStudio.source')}</label>
              <input id="assessment-source" type="text" required minLength={2} maxLength={120}
                className={inputStyle} value={sourceName} onChange={(e) => setSourceName(e.target.value)}
                placeholder={t('assessmentStudio.sourcePlaceholder')} />
            </div>
          </div>
          {framework === 'classical' ? (
            <div>
              <label htmlFor="assessment-assistance" className="label">{t('assessmentStudio.assistance')}</label>
              <select id="assessment-assistance" className={inputStyle} value={assistance}
                onChange={(e) => setAssistance(e.target.value as EducatorAssessmentAssistance)}>
                {ASSISTANCE.map((s) => <option key={s} value={s}>
                  {t('assessmentStudio.assistance_' + s)}
                </option>)}
              </select>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="assessment-score" className="label">{t('assessmentStudio.reportedScore')}</label>
                  <input id="assessment-score" type="number" min={0} max={1000000} step="any"
                    required className={inputStyle} value={score} onChange={(e) => setScore(e.target.value)} />
                </div>
                <div>
                  <label htmlFor="assessment-unit" className="label">{t('assessmentStudio.unit')}</label>
                  <select id="assessment-unit" className={inputStyle} value={scoreUnit}
                    onChange={(e) => setScoreUnit(e.target.value as EducatorAssessmentScoreUnit)}>
                    {UNITS.map((unit) => <option key={unit} value={unit}>
                      {t('assessmentStudio.unit_' + unit)}
                    </option>)}
                  </select>
                </div>
              </div>
              {framework === 'dibels8' && (
                <div>
                  <label htmlFor="assessment-band" className="label">{t('assessmentStudio.reportedBand')}</label>
                  <select id="assessment-band" className={inputStyle} value={band}
                    onChange={(e) => setBand(e.target.value as EducatorAssessmentBand)}>
                    {BANDS.map((value) => <option key={value} value={value}>
                      {t('assessmentStudio.band_' + value)}
                    </option>)}
                  </select>
                  <p className="mt-1 text-xs text-gray-500">{t('assessmentStudio.bandDisclaimer')}</p>
                </div>
              )}
            </>
          )}
          <button type="submit" disabled={saving} className="rounded-lg bg-navy-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? t('assessmentStudio.saving') : t('assessmentStudio.save')}
          </button>
        </form>
      )}

      {message && <p className="mt-3 text-sm text-red-700" role="alert">{message}</p>}
      {loading
        ? <p className="mt-4 text-sm text-gray-500">{t('assessmentStudio.loading')}</p>
        : records.length === 0
          ? <p className="mt-4 text-sm text-gray-500">{t('assessmentStudio.empty')}</p>
          : <ul className="mt-4 space-y-2">
            {records.map((record) => (
              <li key={record.id} className="rounded-xl border border-gray-100 p-3">
                <div className="flex justify-between items-start gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-800">
                      {readableMeasure(record)}
                    </p>
                    <p className="text-xs text-gray-500">
                      {t('assessmentStudio.' + record.framework)} · {record.assessed_on} · {record.source_name}
                    </p>
                    <p className="mt-1 text-sm text-gray-700">
                      {record.framework === 'classical'
                        ? t('assessmentStudio.assistance_' + record.assistance)
                        : `${record.score} — ${t('assessmentStudio.unit_' + record.score_unit)}`}
                    </p>
                    {record.framework === 'dibels8' && record.reported_band &&
                      record.reported_band !== 'not_reported' && (
                        <p className="text-xs text-gray-600">
                          {t('assessmentStudio.asReported')}: {t('assessmentStudio.band_' + record.reported_band)}
                        </p>
                      )}
                    <p className="text-xs text-gray-500 mt-1">{t('assessmentStudio.unverified')}</p>
                  </div>
                  <button type="button" onClick={() => void remove(record.id)}
                    aria-label={t('assessmentStudio.remove')}
                    title={t('assessmentStudio.remove')}
                    className="rounded-lg p-2 text-gray-500 hover:text-red-700 hover:bg-red-50">
                    <Trash2 size={16} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
      }
    </section>
  )
}
