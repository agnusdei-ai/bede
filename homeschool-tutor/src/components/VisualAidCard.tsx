import { useEffect, useState } from 'react'
import { ImageOff, MapPin, Palette } from 'lucide-react'
import type { VisualAidData } from '../types'

/**
 * Renders a picture-study artwork or historical map/artifact.
 *
 * The backend only ever sends a server-validated `wiki_title` (never a raw
 * image URL from the model) — this component resolves that title to an
 * actual image live, client-side, via Wikipedia's public REST summary API.
 * That keeps the curated catalog resilient to file-path changes on the image
 * host, at the cost of a runtime dependency on Wikipedia's API from the
 * child's device. If the lookup fails or returns no image, this degrades to
 * a plain captioned card — never a broken-image icon.
 */
export default function VisualAidCard({ aid }: { aid: VisualAidData }) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setImageUrl(null)

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

  const Icon = aid.category === 'map' ? MapPin : Palette
  const caption = [aid.title, aid.creator].filter(Boolean).join(' — ') + (aid.year ? ` (${aid.year})` : '')

  return (
    <div className="max-w-[85%] rounded-2xl border border-gold-200 bg-white shadow-sm overflow-hidden animate-slide-up">
      {loading && (
        <div className="h-40 bg-parchment-100 animate-pulse-soft flex items-center justify-center">
          <Icon size={22} className="text-gold-400" />
        </div>
      )}

      {!loading && imageUrl && !failed && (
        <img
          src={imageUrl}
          alt={aid.title}
          className="w-full max-h-64 object-contain bg-parchment-50"
          onError={() => setFailed(true)}
        />
      )}

      {!loading && (failed || !imageUrl) && (
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
        <p className="text-sm text-gray-700 leading-relaxed">{aid.description}</p>
      </div>
    </div>
  )
}
