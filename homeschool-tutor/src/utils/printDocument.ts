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
 *   - `printHtml` puts that page in a hidden iframe on this page (nothing a
 *     browser can block), waits for every picture to load or fail, for at
 *     most `IMAGE_WAIT_MS`, prints it, and removes the iframe.
 *
 * The iframe uses `srcdoc`, so it shares this page's origin and its Content
 * Security Policy. That policy already allows what the page needs: inline
 * styles (`style-src 'unsafe-inline'`), and pictures from Wikimedia
 * (`img-src`). No script runs inside the iframe; this page calls its
 * `print()`.
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

const STYLE = `
@page { margin: 0.6in; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body { margin: 0; font-family: Georgia, 'Times New Roman', serif; font-size: 12pt; line-height: 1.4; color: #1d2433; background: #fff; }
@media screen { body { margin: 1rem; } }
h1 { font-size: 17pt; line-height: 1.25; margin: 0 0 0.6rem; }
.who { display: flex; gap: 1.5rem; margin: 0 0 1.2rem; }
.who div { flex: 1; display: flex; align-items: flex-end; gap: 0.4rem; white-space: nowrap; }
.who .fill { flex: 1; border-bottom: 1px solid #555; min-width: 4rem; height: 1.2em; }
ol.items { list-style: none; margin: 0; padding: 0; }
li.item { margin: 0 0 1.1rem; break-inside: avoid; page-break-inside: avoid; }
.prompt { margin: 0 0 0.3rem; overflow-wrap: anywhere; }
.num { font-weight: bold; margin-right: 0.3rem; }
.small { font-size: 10pt; color: #444; margin: 0 0 0.3rem; overflow-wrap: anywhere; }
ul.options { list-style: none; margin: 0.2rem 0 0.4rem; padding-left: 1.2rem; }
ul.options li { margin: 0 0 0.15rem; overflow-wrap: anywhere; }
.line { border-bottom: 1px solid #888; height: 1.9em; }
.choice { display: flex; align-items: flex-end; gap: 0.4rem; margin-top: 0.3rem; }
.choice .line { width: 6rem; }
.ans { font-weight: bold; margin: 0.2rem 0; overflow-wrap: anywhere; }
.diagram { margin: 0.3rem 0; }
.diagram img, .diagram svg { max-width: 100%; height: auto; }
.diagram figure { margin: 0; }
.diagram figcaption { font-size: 9pt; color: #444; }
section.copy + section.copy { break-before: page; page-break-before: always; }
.footer { margin-top: 1rem; font-weight: bold; }
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
    + `<title>${escapeHtml(sheet.title)}</title><style>${STYLE}</style></head><body>${sections}</body></html>`
}

/**
 * Resolve once every picture in `doc` has loaded or failed, or after
 * `timeoutMs`, whichever comes first. A picture that never answers must not
 * stop the page from printing.
 */
export function waitForImages(doc: Document, timeoutMs: number = IMAGE_WAIT_MS): Promise<void> {
  const pending = Array.from(doc.images).filter((img) => !img.complete)
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

const FRAME_ID = 'bede-print-frame'
/** Remove the iframe this long after printing if the browser never says it finished. */
const CLEANUP_MS = 60_000

/**
 * Print `html` from a hidden iframe. Resolves true once `print()` has been
 * called, false if the browser would not let it run.
 */
export function printHtml(html: string, timeoutMs: number = IMAGE_WAIT_MS): Promise<boolean> {
  document.getElementById(FRAME_ID)?.remove()
  const frame = document.createElement('iframe')
  frame.id = FRAME_ID
  frame.title = 'Print'
  frame.setAttribute('aria-hidden', 'true')
  frame.tabIndex = -1
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;'
  return new Promise((resolve) => {
    let started = false
    const start = () => {
      if (started) return
      started = true
      const win = frame.contentWindow
      const doc = frame.contentDocument
      if (!win || !doc) {
        frame.remove()
        resolve(false)
        return
      }
      void waitForImages(doc, timeoutMs).then(() => {
        let removed = false
        const remove = () => {
          if (removed) return
          removed = true
          frame.remove()
        }
        win.addEventListener('afterprint', () => setTimeout(remove, 0), { once: true })
        setTimeout(remove, CLEANUP_MS)
        try {
          win.focus()
          win.print()
          resolve(true)
        } catch {
          remove()
          resolve(false)
        }
      })
    }
    frame.addEventListener('load', start, { once: true })
    // A browser that never fires load for the frame still prints, late.
    setTimeout(start, timeoutMs)
    frame.srcdoc = html
    document.body.appendChild(frame)
  })
}

/** Build the page and print it. */
export function printSheet(sheet: PrintSheet, timeoutMs: number = IMAGE_WAIT_MS): Promise<boolean> {
  return printHtml(buildPrintHtml(sheet), timeoutMs)
}
