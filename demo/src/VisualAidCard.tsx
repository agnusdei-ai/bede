import { useEffect, useState } from 'react'
import { ImageOff, MapPin, Palette, EyeOff } from 'lucide-react'
import type { VisualAidData } from './api'

// Mater Amabilis's picture-study method is specifically: look closely for a
// while, then the picture is put away, then the child narrates what they
// remember — WITHOUT looking again. A card that just stays on screen forever
// defeats the entire exercise, and aid.description below is itself a
// "notice X" priming hint (see data/visual_aids.json) meant for the looking
// phase — left visible during narration, it hands the child the answer
// instead of testing memory. This only applies to picture_study items; a
// history map/artifact is reference material for an ongoing discussion, not
// a memory exercise, so it stays visible the whole time.
const PICTURE_STUDY_VIEW_MS = 25_000

/**
 * Renders a picture-study artwork or historical map/artifact. The catalog only
 * ever supplies a validated wiki_title (never a raw image URL from the model);
 * this resolves it live via Wikipedia's public REST summary API. If that lookup
 * fails or returns no image, this degrades to a plain captioned card rather
 * than a broken-image icon.
 */
export default function VisualAidCard({ aid }: { aid: VisualAidData }) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [putAway, setPutAway] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setImageUrl(null)
    setPutAway(false)

    fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(aid.wiki_title)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('lookup failed'))))
      .then((data) => {
        if (cancelled) return
        const src = data?.thumbnail?.source || data?.originalimage?.source
        if (src) setImageUrl(src)
        else setFailed(true)
      })
      .catch(() => { if (!cancelled) setFailed(true) })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [aid.wiki_title])

  const isPictureStudy = aid.category !== 'map'

  // Starts the moment the image actually renders, not from mount — a slow
  // Wikipedia lookup shouldn't eat into the child's real looking time.
  useEffect(() => {
    if (loading || failed || !imageUrl || !isPictureStudy) return
    const id = setTimeout(() => setPutAway(true), PICTURE_STUDY_VIEW_MS)
    return () => clearTimeout(id)
  }, [loading, failed, imageUrl, isPictureStudy])

  const Icon = aid.category === 'map' ? MapPin : Palette
  const caption = [aid.title, aid.creator].filter(Boolean).join(' — ') + (aid.year ? ` (${aid.year})` : '')

  return (
    <div className="max-w-[85%] rounded-2xl border border-gold-200 bg-white shadow-sm overflow-hidden animate-slide-up">
      {loading && (
        <div className="h-40 bg-parchment-100 animate-pulse-soft flex items-center justify-center">
          <Icon size={22} className="text-gold-400" />
        </div>
      )}
      {!loading && !putAway && imageUrl && !failed && (
        <img
          src={imageUrl}
          alt={aid.title}
          className="w-full max-h-64 object-contain bg-parchment-50"
          onError={() => setFailed(true)}
        />
      )}
      {!loading && putAway && (
        <div className="h-40 bg-gold-50 flex flex-col items-center justify-center gap-1.5 text-gold-600">
          <EyeOff size={20} />
          <span className="text-xs font-medium">Picture put away</span>
        </div>
      )}
      {!loading && !putAway && (failed || !imageUrl) && (
        <div className="h-28 bg-parchment-100 flex flex-col items-center justify-center gap-1.5 text-gold-600">
          <ImageOff size={20} />
          <span className="text-xs">Picture unavailable right now</span>
        </div>
      )}
      <div className="px-4 py-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gold-700 mb-1">
          <Icon size={12} />
          {caption}
        </div>
        {putAway ? (
          <p className="text-sm text-gray-500 italic leading-relaxed">Now tell Bede what you remember, in your own words.</p>
        ) : (
          <p className="text-sm text-gray-700 leading-relaxed">{aid.description}</p>
        )}
      </div>
    </div>
  )
}
