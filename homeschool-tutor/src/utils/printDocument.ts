/**
 * Printing a quiz, an answer key or a practice worksheet, from a phone as
 * well as a desktop.
 *
 * The three print buttons used to open a popup with `window.open`, write the
 * page into it and call `print()` straight away. On an iPhone that failed in
 * three ways: Safari often blocks the popup (and the button then did nothing
 * at all), `print()` ran before any picture had loaded, and a question could
 * be cut in half across two pages. This module replaces all of them:
 *
 *   - `buildPrintHtml` writes one complete page. Every string is escaped
 *     here; the only markup passed in is a diagram from `diagramMarkup`,
 *     which React renders and escapes.
 *   - `printHtml` puts that page on THIS page, inside a shadow root so the
 *     app's own styles cannot reach it, hidden on screen. A print-only rule
 *     hides everything else, so what the printer gets is the sheet alone.
 *     It waits for every picture to load or fail, for at most
 *     `IMAGE_WAIT_MS`, then calls this page's own `print()`.
 *
 * It does not print from an iframe, which an earlier version did: several
 * iOS versions print the page behind a frame instead of the frame, and the
 * frame's load is a wait of its own, which can end the tap Safari needs
 * before it will open the print sheet. With nothing to wait for, `print()`
 * here runs during the tap itself.
 *
 * Nothing new is loaded, so the page's Content Security Policy is unchanged:
 * the sheet's styles are inline (`style-src 'unsafe-inline'`) and its
 * pictures come from Wikimedia (`img-src`), as on screen.
 *
 * The same file lives at homeschool-tutor/src/utils/printDocument.ts and
 * demo/src/printDocument.ts. demo/src/printDocument.test.ts checks the two are
 * identical, byte for byte.
 */

/** One question or practice item. */
export interface PrintItem {
  prompt: string
  /** Short lines under the prompt, such as a passage or the points. */
  details?: string[]
  /** Answer choices, printed as A) B) C). */
  options?: string[]
  /**
   * A picture from `diagramMarkup`, which is already escaped. Never pass
   * model text here: everything else in this module is escaped, this is not.
   */
  diagramHtml?: string
  /** The answer, shown on the answer key. */
  answer?: string
  /** Extra lines under the answer on the key, such as other accepted answers. */
  answerDetails?: string[]
}

export interface PrintLabels {
  name: string
  date: string
  /** The answer key's heading, e.g. "Fractions quiz: answer key". */
  keyTitle: string
}

export interface PrintSheet {
  title: string
  items: PrintItem[]
  labels: PrintLabels
  /**
   * Which copies to print, in order. The student copy has the name and date
   * lines and space to answer; the key shows the answers. When both are
   * printed, the key starts on a new page.
   */
  copies: ReadonlyArray<'student' | 'key'>
  /** Put the name and date lines on the key too (a scored results sheet). */
  nameOnKey?: boolean
  /** A closing line, such as a total. */
  footer?: string
}

/** How long to wait for pictures before printing anyway. */
export const IMAGE_WAIT_MS = 4000
/** Answer lines under a question with no choices. */
export const OPEN_ANSWER_LINES = 3

export function escapeHtml(text: string): string {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

/** "A) first", "B) second", ... */
export function optionLetters(options: ReadonlyArray<string>): string[] {
  return options.map((o, i) => `${String.fromCharCode(65 + i)}) ${o}`)
}

/**
 * The sheet's own styles. Everything is scoped to `.sheet` and sized in pt
 * and em, never rem: the sheet is printed inside the app's page, whose root
 * font size the reader's text-size control changes.
 */
const STYLE = `
:host { all: initial; display: block; }
.sheet { font-family: Georgia, 'Times New Roman', serif; font-size: 12pt; line-height: 1.4; color: #1d2433; background: #fff; -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
.sheet h1 { font-size: 17pt; line-height: 1.25; margin: 0 0 0.5em; font-weight: bold; }
.who { display: flex; gap: 1.5em; margin: 0 0 1.2em; }
.who div { flex: 1; display: flex; align-items: flex-end; gap: 0.4em; white-space: nowrap; }
.who .fill { flex: 1; border-bottom: 1px solid #555; min-width: 4em; height: 1.2em; }
ol.items { list-style: none; margin: 0; padding: 0; }
li.item { margin: 0 0 1.1em; break-inside: avoid; page-break-inside: avoid; }
.prompt { margin: 0 0 0.3em; overflow-wrap: anywhere; }
.num { font-weight: bold; margin-right: 0.3em; }
.small { font-size: 10pt; color: #444; margin: 0 0 0.3em; overflow-wrap: anywhere; }
ul.options { list-style: none; margin: 0.2em 0 0.4em; padding-left: 1.2em; }
ul.options li { margin: 0 0 0.15em; overflow-wrap: anywhere; }
.line { border-bottom: 1px solid #888; height: 1.9em; }
.choice { display: flex; align-items: flex-end; gap: 0.4em; margin-top: 0.3em; }
.choice .line { width: 6em; }
.ans { font-weight: bold; margin: 0.2em 0; overflow-wrap: anywhere; }
.diagram { margin: 0.3em 0; }
.diagram img, .diagram svg { max-width: 100%; height: auto; }
.diagram figure { margin: 0; }
.diagram figcaption { font-size: 9pt; color: #444; }
section.copy + section.copy { break-before: page; page-break-before: always; }
.footer { margin-top: 1em; font-weight: bold; }
`

/** Paper margins, and the white page, when the sheet is opened on its own. */
const PAGE_STYLE = `
@page { margin: 0.6in; }
html, body { margin: 0; background: #fff; }
@media screen { body { margin: 1em; } }
`

function whoLines(labels: PrintLabels): string {
  return `<div class="who"><div>${escapeHtml(labels.name)} <span class="fill"></span></div>`
    + `<div>${escapeHtml(labels.date)} <span class="fill"></span></div></div>`
}

function itemHtml(item: PrintItem, index: number, copy: 'student' | 'key'): string {
  const details = (item.details ?? []).filter(Boolean)
    .map((line) => `<p class="small">${escapeHtml(line)}</p>`).join('')
  const options = item.options?.length
    ? `<ul class="options">${optionLetters(item.options).map((o) => `<li>${escapeHtml(o)}</li>`).join('')}</ul>`
    : ''
  let tail: string
  if (copy === 'key') {
    tail = `<p class="ans">${escapeHtml(item.answer?.trim() ? item.answer : '—')}</p>`
      + (item.answerDetails ?? []).filter(Boolean).map((line) => `<p class="small">${escapeHtml(line)}</p>`).join('')
  } else if (item.options?.length) {
    tail = '<div class="choice"><div class="line"></div></div>'
  } else {
    tail = '<div class="line"></div>'.repeat(OPEN_ANSWER_LINES)
  }
  return `<li class="item"><p class="prompt"><span class="num">${index + 1}.</span> ${escapeHtml(item.prompt)}</p>`
    + `${details}${item.diagramHtml ?? ''}${options}${tail}</li>`
}

/** The whole printable page, as one HTML string. */
export function buildPrintHtml(sheet: PrintSheet): string {
  const sections = sheet.copies.map((copy) => {
    const heading = copy === 'key' ? sheet.labels.keyTitle : sheet.title
    const who = copy === 'student' || sheet.nameOnKey ? whoLines(sheet.labels) : ''
    const items = sheet.items.map((item, i) => itemHtml(item, i, copy)).join('')
    const footer = sheet.footer ? `<p class="footer">${escapeHtml(sheet.footer)}</p>` : ''
    return `<section class="copy ${copy}"><h1>${escapeHtml(heading)}</h1>${who}<ol class="items">${items}</ol>${footer}</section>`
  }).join('')
  return `<!doctype html><html><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>${escapeHtml(sheet.title)}</title><style>${PAGE_STYLE}${STYLE}</style></head>`
    + `<body><div class="sheet">${sections}</div></body></html>`
}

/**
 * Resolve once every picture in `root` has loaded or failed, or after
 * `timeoutMs`, whichever comes first. A picture that never answers must not
 * stop the page from printing.
 */
export function waitForImages(root: ParentNode, timeoutMs: number = IMAGE_WAIT_MS): Promise<void> {
  const pending = Array.from(root.querySelectorAll('img')).filter((img) => !img.complete)
  if (!pending.length) return Promise.resolve()
  return new Promise((resolve) => {
    let left = pending.length
    const timer = setTimeout(resolve, timeoutMs)
    const settle = () => {
      left -= 1
      if (left <= 0) {
        clearTimeout(timer)
        resolve()
      }
    }
    for (const img of pending) {
      img.addEventListener('load', settle, { once: true })
      img.addEventListener('error', settle, { once: true })
    }
  })
}

/** The element that holds the sheet while it prints. */
export const PRINT_ROOT_ID = 'bede-print-root'
const PRINT_RULES_ID = 'bede-print-rules'

/**
 * Added to this page while a sheet is waiting to print: the sheet is hidden
 * on screen, and in print everything but the sheet is hidden, on a plain
 * white page with no height or scrolling the app set for the screen.
 */
const PRINT_RULES = `
@media screen { #${PRINT_ROOT_ID} { display: none !important; } }
@media print {
  @page { margin: 0.6in; }
  html, body { background: #fff !important; margin: 0 !important; padding: 0 !important; height: auto !important; min-height: 0 !important; max-height: none !important; overflow: visible !important; }
  body > *:not(#${PRINT_ROOT_ID}) { display: none !important; }
  #${PRINT_ROOT_ID} { display: block !important; position: static !important; }
}
`

/** Take the sheet and its rules off the page. */
export function clearPrintSheet(): void {
  document.getElementById(PRINT_ROOT_ID)?.remove()
  document.getElementById(PRINT_RULES_ID)?.remove()
}

/**
 * Print `html` (a page from `buildPrintHtml`) from this page. Resolves true
 * once `print()` has been called, false if the browser would not let it run.
 *
 * The sheet stays on the page, hidden, until the browser says printing is
 * finished or the reader next touches the page, never on a timer: iOS keeps
 * its print sheet open for as long as the reader likes, and taking the page
 * away under it would empty the preview.
 */
export function printHtml(html: string, timeoutMs: number = IMAGE_WAIT_MS): Promise<boolean> {
  clearPrintSheet()
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  const styles = Array.from(parsed.querySelectorAll('style')).map((el) => el.textContent ?? '').join('\n')
  const host = document.createElement('div')
  host.id = PRINT_ROOT_ID
  host.setAttribute('aria-hidden', 'true')
  if (!host.attachShadow) return Promise.resolve(false)
  const root = host.attachShadow({ mode: 'open' })
  // The page's own rules (@page, body margins) do nothing inside a shadow
  // root; PRINT_RULES gives the printed page its margins instead.
  root.innerHTML = `<style>${styles}</style>${parsed.body.innerHTML}`
  const rules = document.createElement('style')
  rules.id = PRINT_RULES_ID
  rules.textContent = PRINT_RULES
  document.head.appendChild(rules)
  document.body.appendChild(host)

  const done = () => {
    window.removeEventListener('afterprint', later)
    window.removeEventListener('pointerdown', done, true)
    window.removeEventListener('keydown', done, true)
    if (document.getElementById(PRINT_ROOT_ID) === host) clearPrintSheet()
  }
  const later = () => setTimeout(done, 0)
  const print = (): boolean => {
    window.addEventListener('afterprint', later, { once: true })
    try {
      window.print()
    } catch {
      done()
      return false
    }
    // Added after print(): the tap that started this is still being handled.
    setTimeout(() => {
      window.addEventListener('pointerdown', done, { capture: true, once: true })
      window.addEventListener('keydown', done, { capture: true, once: true })
    }, 0)
    return true
  }
  // Nothing to wait for: print now, while the tap that asked is still live.
  if (!Array.from(root.querySelectorAll('img')).some((img) => !img.complete)) {
    return Promise.resolve(print())
  }
  return waitForImages(root, timeoutMs).then(print)
}

/** Build the page and print it. */
export function printSheet(sheet: PrintSheet, timeoutMs: number = IMAGE_WAIT_MS): Promise<boolean> {
  return printHtml(buildPrintHtml(sheet), timeoutMs)
}
