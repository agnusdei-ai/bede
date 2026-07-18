/**
 * Shared Bede™ brand mark for the demo app. Mirrors
 * homeschool-tutor/src/components/BedeMark.tsx — kept as a separate copy
 * because the demo is a fully standalone Vite app (deployed to GitHub
 * Pages under a sub-path) with no shared source tree, so asset URLs must
 * go through import.meta.env.BASE_URL rather than an absolute root path.
 */

export function BedeWordmark({ className = '' }: { className?: string }) {
  return (
    <span className={className}>
      Bede
      <sup className="text-[0.55em] font-normal align-super ml-0.5">™</sup>
    </span>
  )
}

export function AgnusDeiMark({ className = 'w-10 h-10' }: { className?: string }) {
  return <img src={`${import.meta.env.BASE_URL}agnus-dei-emblem.webp`} alt="Agnus Dei Technologies" className={className} />
}

export function AgnusDeiLogo({ className = 'h-8' }: { className?: string }) {
  return <img src={`${import.meta.env.BASE_URL}agnus-dei-logo.webp`} alt="Agnus Dei Technologies" className={className} />
}

export function TrademarkNotice({ className = '' }: { className?: string }) {
  return (
    <p className={`text-[11px] text-gray-400 leading-relaxed ${className}`}>
      Bede™ and the Agnus Dei logo are trademarks of Agnus Dei Technologies, LLC.
    </p>
  )
}
