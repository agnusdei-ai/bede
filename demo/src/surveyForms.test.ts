/**
 * The four form pages on the public site (the home page's "Request a
 * call", /feedback/, /survey/, /educators/) share one script,
 * `site/assets/feedback-form.js`, which
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
const API_BASE_ASSET = readFileSync(join(SITE, 'assets/api-base.js'), 'utf8')
const BUILD_SCRIPT = readFileSync(join(__dirname, '../../scripts/build_pages_site.sh'), 'utf8')

// The home page's form was missing from this list until the pass that
// rebuilt it around dropdowns and option tiles — it runs the same script
// through the same code path, and is the one form on the site whose
// failure costs a sales lead rather than a survey answer.
const PAGES = [
  { name: 'home', file: 'index.html', category: 'plans', tag: '[Website: onboarding / pricing request]' },
  { name: 'feedback', file: 'feedback/index.html', category: 'cx', tag: '[Website feedback form]' },
  { name: 'survey', file: 'survey/index.html', category: 'beta_survey', tag: '[Beta parent survey]' },
  { name: 'educators', file: 'educators/index.html', category: 'beta_survey', tag: '[Co-op educator survey]' },
] as const

const SURVEYS = PAGES.filter((p) => p.category === 'beta_survey')

/**
 * Load a page's markup into the document and evaluate the shared script
 * against it, exactly as the browser would. The script is an IIFE-free
 * top-level module in a <script src>, so `new Function` reproduces its
 * scope faithfully enough for what is being asserted here.
 */
function mount(file: string, apiBase = '') {
  const html = readFileSync(join(SITE, file), 'utf8')
  document.documentElement.innerHTML = html.replace(/^[\s\S]*?<body>/, '').replace(/<\/body>[\s\S]*$/, '')
  // What assets/api-base.js does on a real page, before the form script
  // runs — empty in the repo, filled in by the build.
  ;(window as unknown as { BEDE_API_BASE: string }).BEDE_API_BASE = apiBase
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
let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  assignedHref = ''
  // Three calls, in order: mint a demo code, exchange it for a token,
  // post the answers.
  fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () =>
      String(url).endsWith('/auth/demo-code') ? { code: 'ABC123' } : { token: 'jwt' },
  }))
  vi.stubGlobal('fetch', fetchMock)
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
  vi.unstubAllGlobals()
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
    // Radio OR checkbox: the home page's form is all checkboxes and a
    // dropdown, having been rebuilt away from free text, and a radio-only
    // search there returns undefined and throws on destructuring rather
    // than reporting anything useful.
    const grouped = [...namedControls(form)].find(([, candidate]) =>
      ['radio', 'checkbox'].includes((candidate as HTMLInputElement).type),
    )
    expect(grouped, 'no grouped control to check the wording of').toBeDefined()
    const [name, el] = grouped!
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

/**
 * MAILTO_SAFE_LENGTH was sized for the twelve-field feedback form. The two
 * surveys are twice that, and with API_BASE unset the mailto hand-off is
 * the ONLY delivery path — so a fully-answered survey overflowing it is an
 * ordinary outcome, not an edge case. The first version of this code
 * answered that by telling the visitor to "shorten the longer answers",
 * which breaks these pages' own promise that nothing they typed is lost,
 * at the worst possible moment.
 */
describe('a survey too long for an email link', () => {
  /** Tick every radio and put a paragraph in every free-text box. */
  function fillCompletely(form: HTMLFormElement) {
    const picked = new Set<string>()
    for (const el of Array.from(form.elements) as HTMLInputElement[]) {
      if (el.type === 'radio' && !picked.has(el.name)) { el.checked = true; picked.add(el.name) }
      else if (el.type === 'checkbox') el.checked = true
      // A <select>'s first option is the "Select a number…" placeholder,
      // whose empty value collect() drops — picking the last one answers
      // the question, which is what "completely" has to mean here.
      else if (el.tagName === 'SELECT') {
        const select = el as unknown as HTMLSelectElement
        select.selectedIndex = select.options.length - 1
      }
      else if (el.tagName === 'TEXTAREA' || el.type === 'text' || el.type === 'email') {
        el.value = 'A realistic paragraph of the kind a parent who cares enough to fill this in actually writes, which is several lines long.'
      }
    }
  }

  it.each(['survey/index.html', 'educators/index.html'])(
    '%s overflows the link when fully answered, which is why the fallback exists',
    (file) => {
      const { form } = mount(file)
      fillCompletely(form)
      form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
      // No mailto was attempted, and none was navigated to.
      expect(form.dataset.mailto).toBeUndefined()
      expect(assignedHref).toBe('')
    },
  )

  it.each(SURVEYS)(
    '$name hands the answers back to be copied rather than losing them',
    ({ file, tag }) => {
      const { form, note } = mount(file)
      fillCompletely(form)
      form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))

      const overflow = form.querySelector('#form-overflow')
      expect(overflow, 'no copy-out offered').not.toBeNull()

      const area = overflow!.querySelector('textarea') as HTMLTextAreaElement
      // The whole assembled message, not a truncated preview: the inbox
      // tag it opens with through to the last answer.
      expect(area.value).toContain(tag)
      expect(area.value).toContain(form.querySelector('legend')!.textContent!.trim())
      expect(area.value.length).toBeGreaterThan(1900)
      expect(area.readOnly).toBe(true)

      // And somewhere to send it.
      expect(overflow!.querySelector('a[href^="mailto:"]')).not.toBeNull()
      expect(note.textContent).not.toMatch(/shorten/i)
    },
  )

  it('does not stack a second copy-out when submitted twice', () => {
    const { form } = mount('survey/index.html')
    fillCompletely(form)
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    expect(form.querySelectorAll('#form-overflow')).toHaveLength(1)
  })

  it('still uses the plain mailto path for a short answer', () => {
    const { form } = mount('survey/index.html')
    ;(form.querySelector('input[type="radio"]') as HTMLInputElement).checked = true
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    expect(form.dataset.mailto).toMatch(/^mailto:/)
    expect(form.querySelector('#form-overflow')).toBeNull()
  })
})

/**
 * The forms post to the same API and the same Resend inbox the in-app
 * feedback does. The API's URL is a per-deployment value, so it is not
 * written into any committed file: assets/api-base.js ships empty and
 * scripts/build_pages_site.sh fills it in from the same
 * VITE_DEMO_API_BASE the demo build already consumes.
 *
 * Both states have to work. Unset is an ordinary outcome (a local
 * preview, a build with no variable) and must fall back rather than
 * throw; set is the real deployment and must actually post.
 */
describe('where the forms send', () => {
  it('ships api-base.js empty, so no deployment URL is committed here', () => {
    expect(API_BASE_ASSET).toMatch(/window\.BEDE_API_BASE\s*=\s*''\s*;/)
    expect(API_BASE_ASSET).not.toMatch(/onrender\.com/)
  })

  it.each(PAGES)('$name loads api-base.js before the form script', ({ file }) => {
    const html = readFileSync(join(SITE, file), 'utf8')
    const base = html.indexOf('/assets/api-base.js')
    const script = html.indexOf('/assets/feedback-form.js')
    expect(base, 'api-base.js is not loaded at all').toBeGreaterThan(-1)
    expect(base).toBeLessThan(script)
  })

  it('takes the mail hand-off when no API base is configured', () => {
    const { form } = mount('survey/index.html')
    ;(form.querySelector('input[type="radio"]') as HTMLInputElement).checked = true
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    expect(form.dataset.mailto).toMatch(/^mailto:/)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('posts to the API when one is configured, and never opens a mail client', async () => {
    const { form } = mount('survey/index.html', 'https://bede-demo-api.onrender.com')
    ;(form.querySelector('input[type="radio"]') as HTMLInputElement).checked = true
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls).toEqual([
      'https://bede-demo-api.onrender.com/auth/demo-code',
      'https://bede-demo-api.onrender.com/auth/login',
      'https://bede-demo-api.onrender.com/feedback',
    ])

    // The category the API files it under, which is what makes the three
    // channels pool. Sent, not merely declared on the form.
    const posted = JSON.parse(String(fetchMock.mock.calls[2][1].body))
    expect(posted.category).toBe('beta_survey')
    expect(posted.message).toContain('[Beta parent survey]')

    expect(form.dataset.mailto).toBeUndefined()
    expect(assignedHref).toBe('')
  })

  it('falls back to mail, losing nothing, when the API cannot be reached', async () => {
    fetchMock.mockRejectedValue(new TypeError('offline'))
    const { form, note } = mount('survey/index.html', 'https://bede-demo-api.onrender.com')
    ;(form.querySelector('input[type="radio"]') as HTMLInputElement).checked = true
    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))

    await vi.waitFor(() => expect(form.dataset.mailto).toMatch(/^mailto:/))
    expect(note.textContent).toMatch(/nothing you typed is lost/i)
  })
})

/**
 * The build is the only thing that fills the URL in, so if it stops doing
 * so the symptom is an inbox that quietly stays empty — nothing errors,
 * and every form still appears to work via the mail hand-off.
 */
describe('the build fills in the API base', () => {
  it('writes api-base.js from the same variable the demo build uses', () => {
    expect(BUILD_SCRIPT).toContain('VITE_DEMO_API_BASE')
    expect(BUILD_SCRIPT).toContain('publish/assets/api-base.js')
    expect(BUILD_SCRIPT).toContain('window.BEDE_API_BASE')
  })

  it('refuses a value that is not a plain https origin', () => {
    // Written verbatim into a script served to every visitor, so it is
    // validated rather than escaped and hoped for.
    expect(BUILD_SCRIPT).toMatch(/grep -Eq .\^https:/)
  })
})

describe('the form pages stay sortable in one inbox', () => {
  it('files both surveys under the same category so they sort together', () => {
    const surveys = SURVEYS
    expect(new Set(surveys.map((p) => p.category))).toEqual(new Set(['beta_survey']))
  })

  it('gives each page a distinct tag so the inbox can still tell them apart', () => {
    const tags = PAGES.map((p) => p.tag)
    expect(new Set(tags).size).toBe(tags.length)
  })
})

/**
 * The home page's form was rebuilt away from free text: "How many
 * children, and their grades?" as one text box became a dropdown plus a
 * set of stage tiles, and the open "What would you like to know?" became
 * topic tiles with one optional comment box under them.
 *
 * That is a change to what the operator receives, not only to what the
 * visitor sees, and the two ways it could go wrong are both silent. A
 * <select> whose only <option> is the "Select a number…" placeholder
 * submits an empty value that collect() drops, so the question vanishes
 * from the email with nothing to show it ever existed. And a group of
 * checkboxes reaches the inbox as one comma-joined line, so a value
 * reworded on the page changes what an answer looks like without changing
 * anything that fails.
 */
describe('the home form delivers its structured answers', () => {
  it('sends a dropdown choice, a multi-select, and the comment box', () => {
    const { form } = mount('index.html')
    ;(form.querySelector('#call_children') as HTMLSelectElement).value = '2'
    for (const value of ['K-2', '6-8']) {
      ;(form.querySelector(`input[name="stages"][value="${value}"]`) as HTMLInputElement).checked = true
    }
    ;(form.querySelector('input[name="topics"][value="Pricing"]') as HTMLInputElement).checked = true
    ;(form.querySelector('#call_details') as HTMLTextAreaElement).value = 'We already read Farmer Boy together.'

    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    const sent = decodeURIComponent(form.dataset.mailto ?? '')

    expect(sent).toContain('How many children are you teaching?: 2')
    // Both ticked stages, joined — not just the first, and not the raw
    // field name.
    expect(sent).toContain('Which stages are they in?: K-2, 6-8')
    expect(sent).toContain('What would you like to know?: Pricing')
    expect(sent).toContain('Anything else we should know?: We already read Farmer Boy together.')
    expect(sent).not.toContain('stages:')
    expect(sent).not.toContain('topics:')
  })

  it('leaves the dropdown out of the message when it was never answered', () => {
    const { form } = mount('index.html')
    ;(form.querySelector('#call_name') as HTMLInputElement).value = 'A Parent'

    form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    const sent = decodeURIComponent(form.dataset.mailto ?? '')

    // The placeholder option's empty value must not arrive as a blank
    // answer to a question nobody chose to answer.
    expect(sent).toContain('Your name: A Parent')
    expect(sent).not.toContain('How many children are you teaching?')
  })

  it('keeps the stage vocabulary the other forms already use', () => {
    // All four forms land in one inbox. The home page asking "K-2" while
    // the feedback page asks "K–2 (Grammar)" would make the same answer
    // two different strings to whoever reads them.
    const home = readFileSync(join(SITE, 'index.html'), 'utf8')
    const feedback = readFileSync(join(SITE, 'feedback/index.html'), 'utf8')
    for (const value of ['K-2', '3-5', '6-8', 'Older']) {
      expect(home).toContain(`name="stages" value="${value}"`)
      expect(feedback).toContain(`name="stages" value="${value}"`)
    }
  })
})
