/**
 * The pure rules of the demo's Practice Coach card, mirrored from
 * homeschool-tutor/src/components/PracticeCoach.tsx (not imported: the demo
 * and the app are separate builds). `practiceCoachParity.test.ts` imports
 * BOTH and asserts they agree, the technique `endpointing.test.ts` and
 * `readingPresentation.test.ts` already use, so the demo cannot demonstrate a
 * gate the product does not have or skip one it does.
 *
 * The one deliberate difference is MAX_PAGES: the demo reads fewer pages per
 * upload than a family may send (homeschool-api's
 * services/practice/demo_store.py MAX_PAGES_PER_UPLOAD, asserted equal by
 * tests/test_practice_demo.py).
 */

export const MAX_PAGES = 3
export const CONFIDENCE_FLOOR = 0.75

export type Mark = 'correct' | 'incorrect' | 'partial' | 'unmarked'
export const MARKS: Mark[] = ['correct', 'incorrect', 'partial', 'unmarked']

/** What the file picker offers. The server decides the real type from the
 *  file's bytes, never from this list or the filename; identical to the app's
 *  so an iPhone HEIC photo and a scanned PDF work in the demo exactly as they
 *  do for a family. */
export const PRACTICE_ACCEPT =
  'image/jpeg,image/png,application/pdf,.pdf,image/heic,image/heif,.heic,.heif'

/** A data: URL from FileReader becomes the bare base64 the API expects. */
export function toBase64Payload(dataUrl: string): string {
  const comma = dataUrl.indexOf(',')
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
}

export function isFlagged(item: { confidence: number; ask_parent?: string | null }): boolean {
  return Boolean(item.ask_parent) || item.confidence < CONFIDENCE_FLOOR
}

interface HasItems {
  sections: { items: { confidence: number; ask_parent?: string | null; teacher_mark: Mark }[] }[]
}

export function flaggedCount(a: HasItems): number {
  return a.sections.reduce((n, s) => n + s.items.filter(isFlagged).length, 0)
}

export function teacherCount(a: HasItems) {
  const marked = a.sections.flatMap((s) => s.items).filter((i) => i.teacher_mark !== 'unmarked')
  return { correct: marked.filter((i) => i.teacher_mark === 'correct').length, total: marked.length }
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!
  ))
}

/** The printable worksheet: prompts and answer lines only. The expected
 *  answers stay on screen for the parent, never on the child's copy. */
export function worksheetHtml(title: string, prompts: string[]): string {
  const rows = prompts.map((p) => `<li><p>${escapeHtml(p)}</p><div class="line"></div></li>`).join('')
  return `<!doctype html><meta charset="utf-8"><title>${escapeHtml(title)}</title>
<style>body{font-family:Georgia,serif;margin:2rem;color:#1d2433}li{margin:0 0 1.4rem}.line{border-bottom:1px solid #999;height:2rem}</style>
<h1>${escapeHtml(title)}</h1><ol>${rows}</ol>`
}
