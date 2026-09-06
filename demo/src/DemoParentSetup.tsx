import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Loader2, Check } from 'lucide-react'

import {
  BIBLE_TRANSLATIONS,
  CHARACTER_VIRTUE_SUGGESTIONS,
  COMPANION_MODES,
  CURRICULUM_RESOURCE_SUGGESTIONS,
  LEARNING_SUPPORT_SUGGESTIONS,
  PUBLIC_DOMAIN_BIBLE_TRANSLATIONS,
  SUBJECTS,
  SUBJECT_LABELS,
  setDemoParentConfig,
  type CompanionMode,
  type DemoParentConfig,
  type Subject,
} from './api'

/**
 * The demo's Parent Setup — the thing a family actually does every morning.
 *
 * The demo used to show a fixed showcase: every subject, no plan, and a gear
 * menu with two client-side toggles, while the product had a whole
 * ParentSetup page. So the one surface a prospective family judges Bede by
 * demonstrated the chat and hid the work — and the setup IS the product for
 * a parent, since it is where they say what their child is learning and what
 * helps that child.
 *
 * Every field here is a real `SessionConfig` field, sent to
 * POST /auth/demo-code/config and read back by `_demo_session_config`, so it
 * shapes the prompt exactly as a real parent's own configuration does. The
 * backend validates by building a real SessionConfig, so this panel cannot
 * offer a combination the product would refuse.
 *
 * Deliberately NOT here, and each for a reason rather than an omission:
 *
 *   - **Security, licensing, AI provider, devices, the audit log.** These
 *     belong to a deployment a family owns; a demo visitor has no deployment.
 *   - **Voice enrollment.** The demo has no voice biometrics to enrol into.
 *   - **The Progress page.** Its mastery cards need history a fifteen-minute
 *     session does not have — the same reason `diagnostic_demo.py` is a
 *     single-session preview.
 *   - **Session length, appearance lock, break rhythm.** Already in the gear
 *     menu beside this panel (`ParentControls.tsx`), and client-side, so
 *     they stay there rather than moving into a form that posts.
 *   - **Reading presentation.** The demo owns letter/line spacing per-device
 *     as a visitor preference; the product has them parent-set. Aligning the
 *     two is its own change (see decision register entry 24) and is not
 *     smuggled in here.
 */

const MAX_RESOURCES = 6
const MAX_VIRTUES = 12
const MAX_SUPPORT = 10

function parseList(raw: string, cap: number): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of raw.split(',')) {
    const item = part.trim()
    if (!item) continue
    const key = item.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
    if (out.length >= cap) break
  }
  return out
}

export default function DemoParentSetup({
  token,
  initial,
  onSaved,
  onClose,
}: {
  token: string
  initial?: DemoParentConfig
  onSaved: (config: DemoParentConfig) => void
  onClose: () => void
}) {
  const { t } = useTranslation()

  const [companion, setCompanion] = useState<CompanionMode>(initial?.companion_mode ?? 'full_plan')
  const [subjects, setSubjects] = useState<Subject[]>(
    initial?.subjects ?? [...COMPANION_MODES[2].subjects],
  )
  const [currentUnit, setCurrentUnit] = useState(initial?.current_unit ?? '')
  const [lessonFocus, setLessonFocus] = useState(initial?.lesson_focus ?? '')
  const [faithEmphasis, setFaithEmphasis] = useState(initial?.faith_emphasis ?? '')
  const [faithTradition, setFaithTradition] = useState(initial?.faith_tradition ?? '')
  const [bible, setBible] = useState(initial?.bible_translation ?? '')
  const [resources, setResources] = useState((initial?.curriculum_resources ?? []).join(', '))
  const [virtues, setVirtues] = useState((initial?.character_virtues ?? []).join(', '))
  const [support, setSupport] = useState((initial?.learning_support ?? []).join(', '))

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // The faith fields follow the product's own gate: a family not using either
  // faith module never sees them (ParentSetup.tsx does the same).
  const faithSubjectOn = subjects.includes('scripture') || subjects.includes('saints')
  // Wider gate for the translation, matching the product: Morning Time
  // already includes daily Bible reading for everyone, and the classical
  // languages quote Scripture beside their own text.
  const bibleGateOn =
    faithSubjectOn ||
    subjects.includes('morning_time') ||
    subjects.includes('latin') ||
    subjects.includes('greek')

  const applyPreset = (mode: CompanionMode) => {
    setCompanion(mode)
    const preset = COMPANION_MODES.find((m) => m.id === mode)
    if (preset) setSubjects([...preset.subjects])
  }

  const toggleSubject = (s: Subject) =>
    setSubjects((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]))

  const appendChip = (
    value: string,
    setValue: (v: string) => void,
    chip: string,
    cap: number,
  ) => {
    const items = parseList(value, cap)
    if (items.some((i) => i.toLowerCase() === chip.toLowerCase())) return
    if (items.length >= cap) return
    setValue([...items, chip].join(', '))
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    const config: DemoParentConfig = {
      subjects,
      companion_mode: companion,
      current_unit: currentUnit.trim() || undefined,
      lesson_focus: lessonFocus.trim() || undefined,
      faith_emphasis: faithSubjectOn ? faithEmphasis.trim() || undefined : undefined,
      faith_tradition: faithSubjectOn ? faithTradition.trim() || undefined : undefined,
      bible_translation: bibleGateOn ? bible || undefined : undefined,
      curriculum_resources: parseList(resources, MAX_RESOURCES),
      character_virtues: parseList(virtues, MAX_VIRTUES),
      learning_support: parseList(support, MAX_SUPPORT),
    }
    try {
      await setDemoParentConfig(token, config)
      setSaved(true)
      onSaved(config)
      setTimeout(onClose, 700)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save these settings')
    } finally {
      setSaving(false)
    }
  }

  const field = 'w-full px-3 py-2 rounded-lg border border-sage-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sage-400'
  const label = 'block text-xs font-semibold text-navy-600 mb-1'
  const chip = 'px-2 py-1 rounded-full border border-navy-200 text-[0.7rem] text-navy-600 hover:bg-navy-50 min-h-[32px]'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/40 backdrop-blur-sm p-3">
      <div className="w-full max-w-lg max-h-[calc(100dvh-1.5rem)] flex flex-col bg-parchment-50 rounded-2xl border border-sage-200 shadow-xl">
        <div className="shrink-0 flex items-center justify-between px-4 py-3 border-b border-sage-200 rounded-t-2xl">
          <div>
            <h2 className="text-base font-display font-bold text-navy-800">
              {t('parentSetup.title', 'Set up the day')}
            </h2>
            <p className="text-xs text-gray-500">
              {t('parentSetup.subtitle', 'The same settings a family uses every morning.')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('parentSetup.close', 'Close setup')}
            title={t('parentSetup.close', 'Close setup')}
            className="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-gray-500 hover:bg-sage-100"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-5">
          {/* Companion mode */}
          <div>
            <span className={label}>{t('parentSetup.howMuch', 'How much should Bede lead?')}</span>
            <div className="flex flex-col gap-1.5">
              {COMPANION_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => applyPreset(m.id)}
                  aria-pressed={companion === m.id}
                  className={`text-left px-3 py-2 rounded-lg border transition-colors min-h-[44px] ${
                    companion === m.id
                      ? 'border-navy-400 bg-navy-50'
                      : 'border-sage-200 bg-white hover:bg-sage-50'
                  }`}
                >
                  <span className="block text-sm font-medium text-navy-700">{m.label}</span>
                  <span className="block text-xs text-gray-500">{m.blurb}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Subjects */}
          <div>
            <span className={label}>
              {t('parentSetup.subjects', 'Subjects for today')}{' '}
              <span className="font-normal text-gray-400">({subjects.length})</span>
            </span>
            <div className="flex flex-wrap gap-1.5">
              {SUBJECTS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => toggleSubject(s)}
                  aria-pressed={subjects.includes(s)}
                  className={`px-2.5 py-1.5 rounded-lg border text-xs min-h-[44px] transition-colors ${
                    subjects.includes(s)
                      ? 'border-navy-400 bg-navy-500 text-white'
                      : 'border-sage-200 bg-white text-navy-600 hover:bg-sage-50'
                  }`}
                >
                  {t(`subjects.${s}`, SUBJECT_LABELS[s])}
                </button>
              ))}
            </div>
            {subjects.length === 0 && (
              <p className="text-xs text-amber-700 mt-1">
                {t('parentSetup.noSubjects', 'Pick at least one subject.')}
              </p>
            )}
          </div>

          {/* Session context */}
          <div className="flex flex-col gap-3">
            <div>
              <label className={label} htmlFor="dps-unit">
                {t('parentSetup.currentUnit', 'What are you already working on?')}
              </label>
              <input
                id="dps-unit"
                value={currentUnit}
                onChange={(e) => setCurrentUnit(e.target.value)}
                maxLength={200}
                placeholder={t('parentSetup.currentUnitHint', 'e.g. reading Farmer Boy together')}
                className={field}
              />
            </div>
            <div>
              <label className={label} htmlFor="dps-focus">
                {t('parentSetup.lessonFocus', "Anything to focus on today?")}
              </label>
              <input
                id="dps-focus"
                value={lessonFocus}
                onChange={(e) => setLessonFocus(e.target.value)}
                maxLength={500}
                placeholder={t('parentSetup.lessonFocusHint', 'e.g. telling a story back in order')}
                className={field}
              />
            </div>
          </div>

          {/* Faith framing — same gate the product uses */}
          {faithSubjectOn && (
            <div className="flex flex-col gap-3">
              <div>
                <label className={label} htmlFor="dps-tradition">
                  {t('parentSetup.faithTradition', 'Your family’s church tradition')}
                </label>
                <input
                  id="dps-tradition"
                  value={faithTradition}
                  onChange={(e) => setFaithTradition(e.target.value)}
                  maxLength={60}
                  placeholder={t('parentSetup.faithTraditionHint', 'e.g. Baptist, Catholic, Non-denominational')}
                  className={field}
                />
              </div>
              <div>
                <label className={label} htmlFor="dps-emphasis">
                  {t('parentSetup.faithEmphasis', 'A verse or virtue to keep in view')}
                </label>
                <input
                  id="dps-emphasis"
                  value={faithEmphasis}
                  onChange={(e) => setFaithEmphasis(e.target.value)}
                  maxLength={500}
                  className={field}
                />
              </div>
            </div>
          )}

          {bibleGateOn && (
            <div>
              <label className={label} htmlFor="dps-bible">
                {t('parentSetup.bible', 'Bible translation')}
              </label>
              <select
                id="dps-bible"
                value={bible}
                onChange={(e) => setBible(e.target.value)}
                className={field}
              >
                <option value="">{t('parentSetup.bibleNone', 'No preference')}</option>
                {BIBLE_TRANSLATIONS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                    {(PUBLIC_DOMAIN_BIBLE_TRANSLATIONS as readonly string[]).includes(b)
                      ? ' — public domain'
                      : ''}
                  </option>
                ))}
              </select>
              <p className="text-[0.7rem] text-gray-500 mt-1">
                {t(
                  'parentSetup.bibleHint',
                  'Bede quotes the public-domain translations freely and paraphrases the rest, citing chapter and verse so you can check the exact wording yourself.',
                )}
              </p>
            </div>
          )}

          {/* Curriculum the family already uses */}
          <div>
            <label className={label} htmlFor="dps-resources">
              {t('parentSetup.resources', 'Curriculum you already use')}
            </label>
            <input
              id="dps-resources"
              value={resources}
              onChange={(e) => setResources(e.target.value)}
              placeholder={t('parentSetup.commaSeparated', 'Comma separated')}
              className={field}
            />
            <div className="flex flex-wrap gap-1 mt-1.5">
              {CURRICULUM_RESOURCE_SUGGESTIONS.map((s) => (
                <button key={s} type="button" className={chip}
                  onClick={() => appendChip(resources, setResources, s, MAX_RESOURCES)}>
                  + {s}
                </button>
              ))}
            </div>
          </div>

          {/* Character virtues */}
          <div>
            <label className={label} htmlFor="dps-virtues">
              {t('parentSetup.virtues', 'Character virtues your family names')}
            </label>
            <input
              id="dps-virtues"
              value={virtues}
              onChange={(e) => setVirtues(e.target.value)}
              placeholder={t('parentSetup.commaSeparated', 'Comma separated')}
              className={field}
            />
            <div className="flex flex-wrap gap-1 mt-1.5">
              {CHARACTER_VIRTUE_SUGGESTIONS.map((s) => (
                <button key={s} type="button" className={chip}
                  onClick={() => appendChip(virtues, setVirtues, s, MAX_VIRTUES)}>
                  + {s}
                </button>
              ))}
            </div>
          </div>

          {/* What helps this child */}
          <div>
            <label className={label} htmlFor="dps-support">
              {t('parentSetup.support', 'What helps this child')}
            </label>
            <input
              id="dps-support"
              value={support}
              onChange={(e) => setSupport(e.target.value)}
              placeholder={t('parentSetup.commaSeparated', 'Comma separated')}
              className={field}
            />
            <div className="flex flex-wrap gap-1 mt-1.5">
              {LEARNING_SUPPORT_SUGGESTIONS.map((s) => (
                <button key={s} type="button" className={chip}
                  onClick={() => appendChip(support, setSupport, s, MAX_SUPPORT)}>
                  + {s}
                </button>
              ))}
            </div>
            <p className="text-[0.7rem] text-gray-500 mt-1">
              {t(
                'parentSetup.supportHint',
                'Changes how a lesson is delivered, never what is taught or the standard the work is held to. Bede never says any of it to your child.',
              )}
            </p>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        <div className="shrink-0 px-4 py-3 border-t border-sage-200 flex items-center justify-end gap-2 rounded-b-2xl">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 min-h-[44px] rounded-lg text-sm text-gray-600 hover:bg-sage-100"
          >
            {t('parentSetup.cancel', 'Cancel')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || subjects.length === 0}
            className="px-4 py-2 min-h-[44px] rounded-lg text-sm font-medium text-white bg-navy-500 hover:bg-navy-600 disabled:opacity-40 flex items-center gap-2"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : saved ? <Check size={16} /> : null}
            {t('parentSetup.save', 'Use this plan')}
          </button>
        </div>
      </div>
    </div>
  )
}
