import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { MapCell, MapScene as Scene } from '../services/api'

/**
 * A practice map, drawn here from the closed set of symbols the server
 * sends (homeschool-api/services/map_practice.py). Nothing on it comes from
 * a model: an unknown symbol is simply not drawn.
 */
const CELL = 64
const LETTERS = 'ABCDE'

const GLYPHS: Record<string, ReactNode> = {
  house: (<><rect x="18" y="30" width="28" height="22" fill="#b5651d" /><polygon points="12,32 32,12 52,32" fill="#7b2d26" /></>),
  tree: (<><rect x="28" y="36" width="8" height="18" fill="#6b4423" /><circle cx="32" cy="26" r="16" fill="#3f7d3a" /></>),
  pond: (<ellipse cx="32" cy="34" rx="22" ry="14" fill="#5b9bd5" stroke="#2f6aa3" strokeWidth="2" />),
  gate: (<><rect x="12" y="20" width="6" height="34" fill="#6b4423" /><rect x="46" y="20" width="6" height="34" fill="#6b4423" /><rect x="18" y="28" width="28" height="5" fill="#8a5a2b" /><rect x="18" y="42" width="28" height="5" fill="#8a5a2b" /></>),
  well: (<><circle cx="32" cy="36" r="16" fill="#9aa0a6" /><circle cx="32" cy="36" r="9" fill="#2f6aa3" /></>),
  barn: (<><rect x="12" y="24" width="40" height="30" fill="#a23b2a" /><polygon points="12,24 32,10 52,24" fill="#7b2d26" /><path d="M24 54 V38 H40 V54 M24 38 L40 54 M40 38 L24 54" stroke="#fff" strokeWidth="2" fill="none" /></>),
  bridge: (<><path d="M8 44 Q32 14 56 44" stroke="#6b4423" strokeWidth="6" fill="none" /><line x1="8" y1="46" x2="56" y2="46" stroke="#6b4423" strokeWidth="4" /></>),
  rock: (<path d="M12 48 Q10 30 26 24 Q44 18 52 34 Q56 48 40 50 Z" fill="#8d8f92" stroke="#5f6163" strokeWidth="2" />),
  flower: (<><rect x="30" y="34" width="4" height="20" fill="#3f7d3a" /><circle cx="32" cy="26" r="6" fill="#e0b400" />{[0, 72, 144, 216, 288].map((a) => (<circle key={a} cx={32 + 11 * Math.cos((a * Math.PI) / 180)} cy={26 + 11 * Math.sin((a * Math.PI) / 180)} r="6" fill="#c2507a" />))}</>),
  bench: (<><rect x="10" y="30" width="44" height="7" fill="#8a5a2b" /><rect x="14" y="37" width="5" height="14" fill="#6b4423" /><rect x="45" y="37" width="5" height="14" fill="#6b4423" /></>),
}

export const KNOWN_SYMBOLS = Object.keys(GLYPHS)
export const cellLabel = (c: MapCell) => `${LETTERS[c[0]]}${c[1] + 1}`
const same = (a: MapCell, b: MapCell) => a[0] === b[0] && a[1] === b[1]
const has = (cells: MapCell[] | undefined, c: MapCell) => !!cells?.some((x) => same(x, c))

export function Glyph({ symbol, size = 40 }: { symbol: string; size?: number }) {
  if (!GLYPHS[symbol]) return null
  return <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">{GLYPHS[symbol]}</svg>
}

export default function MapScene({
  scene, onTap, disabled = false, guide, marked, revealed, picked, tilted = false, small = false,
}: {
  scene: Scene
  onTap?: (cell: MapCell) => void
  disabled?: boolean
  guide?: MapCell[]
  marked?: MapCell
  revealed?: MapCell
  picked?: MapCell
  tilted?: boolean
  small?: boolean
}) {
  const { t } = useTranslation()
  const pad = scene.grid_labels ? 22 : 0
  const w = scene.cols * CELL + pad
  const h = scene.rows * CELL + pad
  const cells: MapCell[] = []
  for (let r = 0; r < scene.rows; r += 1) for (let c = 0; c < scene.cols; c += 1) cells.push([c, r])
  const itemAt = (c: MapCell) => scene.items.find((i) => i.col === c[0] && i.row === c[1])?.symbol
  const name = (c: MapCell) => {
    const symbol = itemAt(c)
    const ground = has(scene.water, c) ? t('mapPractice.ground.water') : ''
    const what = symbol && GLYPHS[symbol] ? t(`mapPractice.symbol.${symbol}`) : ground
    return what ? `${t('mapPractice.square', { label: cellLabel(c) })}: ${what}` : t('mapPractice.square', { label: cellLabel(c) })
  }
  const land = scene.style === 'picture' ? '#dcebc6' : '#f4ecd8'

  return (
    <div className="flex flex-col items-center gap-2" style={{ perspective: 700 }}>
      <div className="relative">
        <svg
          viewBox={`0 0 ${w} ${h}`} role="group" aria-label={t('mapPractice.mapLabel')}
          className={`${small ? 'w-36' : 'w-full max-w-md'} h-auto rounded-xl border border-sage-300 shadow-sm transition-transform duration-1000 motion-reduce:transition-none`}
          style={{ transform: tilted ? 'rotateX(58deg)' : 'rotateX(0deg)', width: small ? undefined : Math.min(w, 448) }}
        >
          {scene.grid_labels && Array.from({ length: scene.cols }, (_, c) => (
            <text key={`c${c}`} x={pad + c * CELL + CELL / 2} y={16} textAnchor="middle" fontSize="14" fontWeight="600" fill="#1f2a44">{LETTERS[c]}</text>
          ))}
          {scene.grid_labels && Array.from({ length: scene.rows }, (_, r) => (
            <text key={`r${r}`} x={10} y={pad + r * CELL + CELL / 2 + 5} textAnchor="middle" fontSize="14" fontWeight="600" fill="#1f2a44">{r + 1}</text>
          ))}
          {cells.map((c) => {
            const x = pad + c[0] * CELL
            const y = pad + c[1] * CELL
            const symbol = itemAt(c)
            const tappable = !!onTap && !disabled
            const isWater = has(scene.water, c)
            const isPath = has(scene.path, c)
            return (
              <g
                key={`${c[0]}-${c[1]}`}
                role={onTap ? 'button' : undefined}
                tabIndex={tappable ? 0 : undefined}
                aria-label={onTap ? name(c) : undefined}
                aria-disabled={onTap && disabled ? true : undefined}
                data-cell={cellLabel(c)}
                onClick={tappable ? () => onTap(c) : undefined}
                onKeyDown={tappable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onTap(c) } } : undefined}
                style={{ cursor: tappable ? 'pointer' : 'default' }}
              >
                <rect
                  x={x} y={y} width={CELL} height={CELL}
                  fill={isWater ? '#a9cdee' : isPath ? '#e3c48e' : land}
                  stroke={scene.style === 'map' ? '#b9ad8f' : 'none'} strokeWidth="1"
                />
                {has(guide, c) && <rect x={x + 3} y={y + 3} width={CELL - 6} height={CELL - 6} fill="#f6d55c" opacity="0.35" rx="6" data-guide="" />}
                {symbol && GLYPHS[symbol] && <g transform={`translate(${x},${y})`}>{GLYPHS[symbol]}</g>}
                {marked && same(marked, c) && <rect x={x + 3} y={y + 3} width={CELL - 6} height={CELL - 6} fill="none" stroke="#1f2a44" strokeWidth="3" strokeDasharray="6 4" rx="6" data-marked="" />}
                {picked && same(picked, c) && <rect x={x + 3} y={y + 3} width={CELL - 6} height={CELL - 6} fill="none" stroke="#c2507a" strokeWidth="4" rx="6" />}
                {revealed && same(revealed, c) && <rect x={x + 3} y={y + 3} width={CELL - 6} height={CELL - 6} fill="none" stroke="#2e7d32" strokeWidth="5" rx="6" data-revealed="" />}
              </g>
            )
          })}
        </svg>
        {scene.compass !== 'none' && !small && (
          <svg viewBox="0 0 64 64" className="absolute -top-3 -right-3 w-14 h-14 bg-white rounded-full border border-sage-300 shadow" role="img" aria-label={t('mapPractice.compassLabel')}>
            <polygon points="32,8 38,32 32,28 26,32" fill="#a23b2a" />
            <polygon points="32,56 38,32 32,36 26,32" fill="#9aa0a6" />
            <text x="32" y="9" textAnchor="middle" fontSize="9" fontWeight="700" fill="#1f2a44" dy="-1">{t('mapPractice.compass.n')}</text>
            {scene.compass === 'labeled' && (
              <>
                <text x="32" y="63" textAnchor="middle" fontSize="9" fontWeight="700" fill="#1f2a44">{t('mapPractice.compass.s')}</text>
                <text x="58" y="35" textAnchor="middle" fontSize="9" fontWeight="700" fill="#1f2a44">{t('mapPractice.compass.e')}</text>
                <text x="6" y="35" textAnchor="middle" fontSize="9" fontWeight="700" fill="#1f2a44">{t('mapPractice.compass.w')}</text>
              </>
            )}
          </svg>
        )}
      </div>
      {scene.key && !small && (
        <ul aria-label={t('mapPractice.keyLabel')} className="flex flex-wrap justify-center gap-x-4 gap-y-1 rounded-lg border border-sage-200 bg-white px-3 py-2 text-sm text-gray-700">
          {scene.items.filter((i) => GLYPHS[i.symbol]).map((i) => (
            <li key={i.symbol} className="flex items-center gap-1.5">
              <Glyph symbol={i.symbol} size={24} />{t(`mapPractice.symbol.${i.symbol}`)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The same things seen from the side, left to right (level K, "from above"). */
export function SideView({ symbols }: { symbols: string[] }) {
  const { t } = useTranslation()
  return (
    <div role="img" aria-label={t('mapPractice.sideViewLabel')} className="flex items-end justify-center gap-6 border-b-4 border-sage-400 px-6 pt-2">
      {symbols.map((s) => <Glyph key={s} symbol={s} size={56} />)}
    </div>
  )
}
