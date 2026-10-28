import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../..')
const read = (path: string) => readFileSync(resolve(root, path), 'utf8')
const pages = [
  ['homeschool', 'family-questions', 5],
  ['educators', 'coop-questions', 4],
  ['schools', 'school-questions', 8],
] as const
const words = (text: string) => text.trim().split(/\s+/).length

describe('concise copy and audience-specific FAQs', () => {
  it('answers the classical digital learning query without claiming school enrollment', () => {
    document.documentElement.innerHTML = read('site/homeschool/index.html')
    const intro = document.querySelector('.classical-hero-copy > p:not(.classical-kicker)')!
    expect(intro.textContent).toContain('classical digital learning program for K–8 homeschool families')
    for (const subject of ['reading', 'writing', 'mathematics', 'reasoning']) {
      expect(intro.textContent).toContain(subject)
    }
    const texas = document.getElementById('texas-classical-learning')!
    expect(texas.querySelector('summary')!.textContent).toBe(
      'Is there a classical digital program for my eight-year-old in Texas?',
    )
    expect(texas.textContent).toContain('Families arrange school enrollment or homeschooling separately')
    expect(texas.querySelector('a[href="/inquire/?audience=homeschool"]')).not.toBeNull()
    expect(texas.querySelector('a[href="https://tea.texas.gov/families-and-students/finding-school-your-child/home-schooling"]')).not.toBeNull()
    expect(document.querySelector('meta[property="og:title"]')!.getAttribute('content')).toBe(document.title)
    expect(document.querySelector('meta[property="og:description"]')!.getAttribute('content')).toBe(
      document.querySelector('meta[name="description"]')!.getAttribute('content'),
    )
    const sitemap = new DOMParser().parseFromString(read('site/sitemap.xml'), 'application/xml')
    expect(sitemap.querySelector('parsererror')).toBeNull()
    expect([...sitemap.querySelectorAll('loc')].filter(node =>
      node.textContent === 'https://agnusdei.ai/homeschool/',
    )).toHaveLength(1)
  })

  it('uses the owner’s short inquiry fallback with a single clear email link', () => {
    document.documentElement.innerHTML = read('site/inquire/index.html')
    const help = document.querySelector('.inquiry-help')!
    expect(help.textContent).toBe('If the form is unavailable, please feel free to email info@agnusdei.ai.')
    expect(help.querySelectorAll('a')).toHaveLength(1)
    expect(help.querySelector('a')!.getAttribute('href')).toBe('mailto:info@agnusdei.ai')
    expect(document.querySelector('input[name="consent"][required]')).not.toBeNull()
    expect(document.querySelector('main a[href="/privacy/"]')).not.toBeNull()
    expect(document.querySelector('main')!.textContent).toContain('student names, records, or sensitive information')
    for (const hint of document.querySelectorAll('.survey-hint')) expect(words(hint.textContent!)).toBeLessThanOrEqual(16)
  })

  it.each(pages)('puts %s guidance in closed, accessible audience FAQs', (route, id, count) => {
    document.documentElement.innerHTML = read(`site/${route}/index.html`)
    const section = document.getElementById(id)!
    expect(section).not.toBeNull()
    expect(document.getElementById(section.getAttribute('aria-labelledby')!)).not.toBeNull()
    const questions = section.querySelectorAll('details')
    expect(questions).toHaveLength(count)
    for (const question of questions) {
      expect(question.open).toBe(false)
      expect(question.querySelector('summary')!.textContent).toBeTruthy()
      expect(question.querySelector('p')!.textContent).toBeTruthy()
      expect(question.classList.contains('streamlined-detail')).toBe(true)
    }
  })

  it.each(pages)('links the central FAQ to the real %s section', (route, id) => {
    document.documentElement.innerHTML = read('site/faq/index.html')
    expect(document.querySelector(`a[href="/${route}/#${id}"]`)).not.toBeNull()
  })

  it('keeps school structured data identical to the shortened visible answers', () => {
    document.documentElement.innerHTML = read('site/schools/index.html')
    const schema = JSON.parse(document.querySelector('script[type="application/ld+json"]')!.textContent!)
    const visible = [...document.querySelectorAll('#school-questions details')].map(detail => ({
      name: detail.querySelector('summary')!.textContent,
      answer: detail.querySelector('p')!.textContent,
    }))
    expect(schema.mainEntity.map((item: { name: string; acceptedAnswer: { text: string } }) => ({
      name: item.name, answer: item.acceptedAnswer.text,
    }))).toEqual(visible)
    expect(document.querySelector('.hero-footnote')!.textContent).toContain('No direct student tutoring')
    expect(document.getElementById('school-questions')!.textContent).toContain('nondevotional academic scope')
    expect(document.getElementById('school-questions')!.textContent).toContain('12-month commitment')
  })

  it('keeps family setup and faith boundaries available without extra main-section warnings', () => {
    document.documentElement.innerHTML = read('site/homeschool/index.html')
    const faq = document.getElementById('family-questions')!.textContent!
    expect(faq).toContain('up to six children')
    expect(faq).toContain('separately configured, approved access')
    expect(faq).toContain('Faith and character are never scored')
    expect(faq).toContain('not a spiritual advisor')
    expect(document.querySelector('a[href="/faq/#family-traditions"]')).not.toBeNull()
  })

  it('routes the legacy feedback page to the single survey and inquiry instead of stale form copy', () => {
    document.documentElement.innerHTML = read('site/feedback/index.html')
    expect(document.querySelector('main a[href="/survey/"]')).not.toBeNull()
    expect(document.querySelector('main a[href="/inquire/"]')).not.toBeNull()
    expect(document.querySelector('main')!.textContent).not.toMatch(/question below|two fields filled|built and tested in one family/)
  })
})
