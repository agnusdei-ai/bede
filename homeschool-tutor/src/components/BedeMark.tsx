/**
 * Shared Bede™ brand mark. Centralized so the trademark symbol and the
 * Agnus Dei Technologies, LLC attribution stay consistent everywhere the
 * Bede name or logo appears as a brand, rather than being retyped per page.
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
  return <img src="/agnus-dei.svg" alt="Agnus Dei Technologies" className={className} />
}

export function TrademarkNotice({ className = '' }: { className?: string }) {
  return (
    <p className={`text-[11px] text-gray-400 leading-relaxed ${className}`}>
      Bede™ and the Agnus Dei logo are trademarks of Agnus Dei Technologies, LLC.
    </p>
  )
}
