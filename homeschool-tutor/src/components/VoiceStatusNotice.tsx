import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Volume2, VolumeX } from 'lucide-react'
import { fetchVoiceStatus, type VoiceStatus } from '../services/api'

/**
 * Tells a parent whether Bede speaks aloud on this computer, and where Bede's
 * voice runs. Every feature speaks only in Bede's own voice; with none set
 * up, Bede is silent rather than using the browser's voice (owner decisions
 * 2026-11-18, docs/DECISIONS.md entry 46), and this is where a parent learns
 * why. Shows nothing when the status cannot be read.
 */
export default function VoiceStatusNotice({ token }: { token: string }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<VoiceStatus | null>(null)

  useEffect(() => {
    let live = true
    fetchVoiceStatus(token).then((s) => { if (live) setStatus(s) })
    return () => { live = false }
  }, [token])

  if (!status) return null
  const key = !status.configured ? 'none' : status.where === 'local' ? 'local' : 'cloud'
  const Icon = status.configured ? Volume2 : VolumeX
  return (
    <section
      data-testid="voice-status"
      data-voice={key}
      className="rounded-2xl border border-parchment-200 bg-white px-4 py-3 text-sm text-navy-700"
    >
      <h2 className="flex items-center gap-2 font-semibold text-navy-800">
        <Icon className="h-4 w-4" aria-hidden="true" />
        {t('voiceStatus.title')}
      </h2>
      <p className="mt-1">{t(`voiceStatus.${key}`)}</p>
    </section>
  )
}
