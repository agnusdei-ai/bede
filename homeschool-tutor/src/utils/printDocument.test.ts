import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  IMAGE_WAIT_MS,
  OPEN_ANSWER_LINES,
  buildPrintHtml,
  printHtml,
  waitForImages,
  type PrintSheet,
} from './printDocument'

const labels = { name: 'Name', date: 'Date', keyTitle: 'Plants quiz: answer key' }

function sheet(overrides: Partial<PrintSheet> = {}): PrintSheet {
  return {
    title: 'Plants quiz',
    labels,
    copies: ['student'],
    items: [
      { prompt: 'What do leaves need?', answer: 'sunlight' },
      { prompt: 'Which is a root?', options: ['carrot', 'apple'], answer: 'A' },
    ],
    ...overrides,
  }
}

const count = (html: string, needle: string) => html.split(needle).length - 1

describe('buildPrintHtml', () => {
  it('escapes every piece of text it is given', () => {
    const html = buildPrintHtml(sheet({
      title: 'Quiz <b>one</b>',
      labels: { name: 'N<a>', date: 'D"', keyTitle: "K'" },
      copies: ['student', 'key'],
      items: [{
        prompt: '<script>alert(1)</script> & more',
        details: ['<img src=x onerror=alert(1)>'],
        options: ['"quoted"', '<i>x</i>'],
        answer: '</p><script>',
        answerDetails: ['<u>also</u>'],
      }],
    }))
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img src=x')
    expect(html).not.toContain('<i>x</i>')
    expect(html).not.toContain('<u>')
    expect(html).not.toContain('<b>one')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt; &amp; more')
    expect(html).toContain('A) &quot;quoted&quot;')
    expect(html).toContain('N&lt;a&gt;')
    expect(html).toContain('K&#39;')
  })

  it('passes a diagram through as markup, because diagramMarkup has already escaped it', () => {
    const html = buildPrintHtml(sheet({ items: [{ prompt: 'Shaded?', diagramHtml: '<div class="diagram"><svg></svg></div>' }] }))
    expect(html).toContain('<div class="diagram"><svg></svg></div>')
  })

  it('puts name and date lines on the student copy only', () => {
    const student = buildPrintHtml(sheet())
    expect(student).toContain('Name <span class="fill">')
    expect(student).toContain('Date <span class="fill">')
    expect(student).not.toContain('class="ans"')
    expect(student).not.toContain('sunlight')

    const key = buildPrintHtml(sheet({ copies: ['key'] }))
    expect(key).not.toContain('class="fill"')
    expect(key).toContain('<h1>Plants quiz: answer key</h1>')
    expect(key).toContain('<p class="ans">sunlight</p>')

    const results = buildPrintHtml(sheet({ copies: ['key'], nameOnKey: true }))
    expect(results).toContain('Name <span class="fill">')
  })

  it('gives an open question answer lines and a choice question one short line', () => {
    const html = buildPrintHtml(sheet({ items: [{ prompt: 'Open?' }] }))
    expect(count(html, '<div class="line"></div>')).toBe(OPEN_ANSWER_LINES)
    const choice = buildPrintHtml(sheet({ items: [{ prompt: 'Pick', options: ['a', 'b', 'c'] }] }))
    expect(count(choice, '<div class="line"></div>')).toBe(1)
    expect(choice).toContain('<li>A) a</li><li>B) b</li><li>C) c</li>')
  })

  it('numbers the questions and keeps each one on a single page', () => {
    const html = buildPrintHtml(sheet())
    expect(html).toContain('<span class="num">1.</span> What do leaves need?')
    expect(html).toContain('<span class="num">2.</span> Which is a root?')
    expect(html).toMatch(/li\.item \{[^}]*break-inside: avoid;[^}]*page-break-inside: avoid;/)
    expect(html).toContain('@page { margin:')
  })

  it('starts the answer key on a new page when both are printed together', () => {
    const html = buildPrintHtml(sheet({ copies: ['student', 'key'] }))
    expect(html.indexOf('<section class="copy student">')).toBeLessThan(html.indexOf('<section class="copy key">'))
    expect(html).toMatch(/section\.copy \+ section\.copy \{ break-before: page; page-break-before: always; \}/)
  })

  it('prints a dash for an answer that was left empty, and a footer when there is one', () => {
    const html = buildPrintHtml(sheet({ copies: ['key'], items: [{ prompt: 'Q', answer: ' ' }], footer: 'Total: 2 of 2' }))
    expect(html).toContain('<p class="ans">—</p>')
    expect(html).toContain('<p class="footer">Total: 2 of 2</p>')
  })
})

describe('waitForImages', () => {
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

  function pendingImage(): HTMLImageElement {
    const img = document.createElement('img')
    Object.defineProperty(img, 'complete', { value: false })
    document.body.appendChild(img)
    return img
  }

  it('resolves at once when every picture is already there', async () => {
    const img = document.createElement('img')
    Object.defineProperty(img, 'complete', { value: true })
    document.body.appendChild(img)
    await expect(waitForImages(document, 10_000)).resolves.toBeUndefined()
  })

  it('waits for every picture to load or fail', async () => {
    const a = pendingImage()
    const b = pendingImage()
    let done = false
    void waitForImages(document, 10_000).then(() => { done = true })
    a.dispatchEvent(new Event('load'))
    await Promise.resolve()
    expect(done).toBe(false)
    b.dispatchEvent(new Event('error'))
    await vi.waitFor(() => expect(done).toBe(true))
  })

  it('gives up on a picture that never answers, so the page still prints', async () => {
    vi.useFakeTimers()
    pendingImage()
    let done = false
    void waitForImages(document).then(() => { done = true })
    await vi.advanceTimersByTimeAsync(IMAGE_WAIT_MS - 1)
    expect(done).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(done).toBe(true)
  })

  it('waits a few seconds at most', () => {
    expect(IMAGE_WAIT_MS).toBeGreaterThan(0)
    expect(IMAGE_WAIT_MS).toBeLessThanOrEqual(5000)
  })
})

describe('printHtml', () => {
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })

  /** Catch the iframe as it is added, and stand in for the browser's print(). */
  function captureFrame(print: () => void) {
    const frames: HTMLIFrameElement[] = []
    const append = document.body.appendChild.bind(document.body)
    vi.spyOn(document.body, 'appendChild').mockImplementation(<T extends Node>(node: T): T => {
      const added = append(node)
      if (node instanceof HTMLIFrameElement) {
        frames.push(node)
        node.contentWindow!.print = print
        node.contentWindow!.focus = () => {}
      }
      return added
    })
    return frames
  }

  it('prints from a hidden iframe on this page, never a popup', async () => {
    const open = vi.spyOn(window, 'open')
    const print = vi.fn()
    const frames = captureFrame(print)
    const result = printHtml('<p>Hello</p>', 50)
    expect(frames).toHaveLength(1)
    expect(frames[0].srcdoc).toBe('<p>Hello</p>')
    expect(frames[0].getAttribute('aria-hidden')).toBe('true')
    await expect(result).resolves.toBe(true)
    expect(print).toHaveBeenCalledTimes(1)
    expect(open).not.toHaveBeenCalled()
  })

  it('removes the iframe once printing is done', async () => {
    const frames = captureFrame(vi.fn())
    await printHtml('<p>x</p>', 50)
    expect(document.body.contains(frames[0])).toBe(true)
    frames[0].contentWindow!.dispatchEvent(new Event('afterprint'))
    await vi.waitFor(() => expect(document.body.contains(frames[0])).toBe(false))
  })

  it('replaces an earlier print iframe rather than piling them up', async () => {
    const frames = captureFrame(vi.fn())
    await printHtml('<p>one</p>', 50)
    await printHtml('<p>two</p>', 50)
    expect(document.body.contains(frames[0])).toBe(false)
    expect(document.querySelectorAll('iframe')).toHaveLength(1)
  })

  it('reports failure, and cleans up, when the browser refuses to print', async () => {
    const frames = captureFrame(() => { throw new Error('blocked') })
    await expect(printHtml('<p>x</p>', 50)).resolves.toBe(false)
    expect(document.body.contains(frames[0])).toBe(false)
  })
})
