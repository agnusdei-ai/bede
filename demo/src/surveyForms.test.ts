/**
 * The three form pages on the public site (/feedback/, /survey/,
 * /educators/) share one script, `site/assets/feedback-form.js`, which
 * reads each question's wording out of that page's own markup rather than
 * from a map inside the script. That removed a real duplication: the old
 * version carried a hardcoded field-name-to-label map, so a question
 * reworded on the page kept arriving in the operator's inbox under its old
 * wording, silently, with nothing to catch it.
 *
 * Reading from the DOM only helps if it actually resolves every control,
 * though. A control the script cannot find a question for still submits
 * its answer, just filed under a bare field name like "vs_parent" - the
 * same class of silent wrongness, moved. So this loads the real pages into
 * a real DOM, runs the real script, and asserts the assembled message.
 *
 * Same shape and reasoning as privacyInventory.test.ts beside it: an
 * assertion about site/ living in the package that has a DOM to assert
 * with. See docs/BETA_SURVEY.md's "Keeping the three channels honest".
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const SITE = join(__dirname, '../../site')
const SCRIPT = readFileSync(join(SITE, 'assets/feedback-form.js'), 'utf8')

const PAGES = [
  { name: 'feedback', file: 'feedback/index.html', category: 'cx', tag: '[Website feedback form]' },
  { name: 'survey', file: 'survey/index.html', category: 'beta_survey', tag: '[Beta parent survey]' },
  { name: 'educators', file: 'educators/index.html', category: 'beta_survey', tag: '[Co-op educator survey]' },
] as const

/**
 * Load a page's markup into the document and evaluate the shared script
 * against it, exactly as the browser would. The script is an IIFE-free
 * top-level module in a <script src>, so `new Function` reproduces its
 * scope faithfully enough for what is being asserted here.
 */
function mount(file: string) {
  const html = readFileSync(join(SITE, file), 'utf8')
  document.documentElement.innerHTML = html.replace(/^[\s\S]*?<body>/, '').replace(/<\/body>[\s\S]*$/, '')
  // eslint-disable-next-line no-new-func
  new Function(SCRIPT)()
  const form = document.querySelector('form[data-category]') as HTMLFormElement
  const note = document.getElementById('form-note') as HTMLElement
  return { form, note }
}

/** Every named control on the page, one representative element per name. */
function namedControls(form: HTMLFormElement) {
  const seen = new Map<string, Element>()
  for (const el of Array.from(form.elements) as HTMLInputElement[]) {
    if (el.name && !seen.has(el.name)) seen.set(el.name, el)
  }
  return seen
}

let assignedHref = ''

beforeEach(() => {
  assignedHref = ''
  // jsdom refuses real navigation ("Not implemented: navigation"), and the
  // mailto hand-off is the path under test here, so capture it instead.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      get href() { return assignedHref },
      set href(value: string) { assignedHref = value },
    },
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  document.documentElement.innerHTML = ''
})

describe.each(PAGES)('$name page', ({ file, category, tag }) => {
  it('declares the category and inbox tag the script reads', () => {
    const { form } = mount(file)
    expect(form.dataset.category).toBe(category)
    expect(form.dataset.tag).toBe(tag)
    expect(form.dataset.mailSubject).toBeTruthy()
  })

  it('has a #form-note for the script to report into', () => {
    const { note } = mount(file)
    expect(note).not.toBeNull()
  })

  /**
   * The load-bearing one. Every control must resolve to real question
   * text - a fieldset's <legend> or a <label for> - never to its own bare
   * field name, which is what the fallback in questionFor() produces and
   * which would reach the inbox as "price_no: $80".
   */
  it('resolves every control to readable question text, not a field name', () => {
    const { form } = mount(file)
    const controls = namedControls(form)
    expect(controls.size).toBeGreaterThan(5)

    for (const [name, el] of controls) {
      const fieldset = el.closest('fieldset')
      const legend = fieldset?.querySelector('legend')?.textContent?.trim()
      const labelled = form.querySelector(`label[for="${el.id}"]`)?.textContent?.trim()
      const question = legend || labelled
      expect(question, `control "${name}" has no legend or <label for>`).toBeTruthy()
      expect(question).not.toBe(name)
    }
  })

  it('sends nothing and says so when the form is empty', () => {
    const { form, note } = mount(file)
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    expect(note.textContent).toContain('Nothing filled in yet')
    expect(assignedHref).toBe('')
  })

  it('puts the question wording, not the field name, into the message', () => {
    const { form } = mount(file)
    const [name, el] = [...namedControls(form)].find(
      ([, candidate]) => (candidate as HTMLInputElement).type === 'radio',
    )!
    const input = form.querySelector(`input[name="${name}"]`) as HTMLInputElement
    input.checked = true
    const expectedQuestion = el.closest('fieldset')!.querySelector('legend')!.textContent!.trim()

    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))

    // API_BASE is '' as shipped, so this takes the mailto hand-off path.
    const sent = decodeURIComponent(form.dataset.mailto ?? '')
    expect(sent).toContain(tag)
    expect(sent).toContain(`${expectedQuestion}: ${input.value}`)
    expect(sent).not.toContain(`${name}:`)
  })
})

describe('the three pages stay pooled in one inbox', () => {
  it('files both surveys under the same category so they sort together', () => {
    const surveys = PAGES.filter((p) => p.name !== 'feedback')
    expect(new Set(surveys.map((p) => p.category))).toEqual(new Set(['beta_survey']))
  })

  it('gives each page a distinct tag so the inbox can still tell them apart', () => {
    const tags = PAGES.map((p) => p.tag)
    expect(new Set(tags).size).toBe(tags.length)
  })
})
