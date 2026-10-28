import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = resolve(import.meta.dirname, '../..')
const read = (name: string) => readFileSync(resolve(root, name), 'utf8')
const audiences = ['homeschool', 'schools', 'educators']

describe('audience discovery and source-backed descriptions', () => {
  it('lists every canonical static content page and the separately built tour once', () => {
    const sitemap = new DOMParser().parseFromString(read('site/sitemap.xml'), 'application/xml')
    expect(sitemap.querySelector('parsererror')).toBeNull()
    const urls = [...sitemap.querySelectorAll('loc')].map(node => node.textContent!)
    expect(new Set(urls).size).toBe(urls.length)
    const entries = readdirSync(resolve(root, 'site'), { withFileTypes: true })
    const pages = ['site/index.html', ...entries.filter(entry => entry.isDirectory())
      .map(entry => `site/${entry.name}/index.html`)
      .filter(name => existsSync(resolve(root, name)))]
    for (const name of pages) {
      const doc = new DOMParser().parseFromString(read(name), 'text/html')
      if (doc.querySelector('meta[http-equiv="refresh" i]')) continue
      const canonical = doc.querySelector('link[rel="canonical"]')?.getAttribute('href')
      if (canonical) expect(urls, name).toContain(canonical)
    }
    expect(urls).toContain('https://agnusdei.ai/bede/tour/')
    expect(urls).not.toContain('https://agnusdei.ai/trackers/')
    for (const url of urls) {
      expect(new URL(url).origin).toBe('https://agnusdei.ai')
      expect(new URL(url).search).toBe('')
      expect(new URL(url).hash).toBe('')
    }
  })

  it.each(audiences)('makes %s scope and evidence discoverable in static HTML', route => {
    const doc = new DOMParser().parseFromString(read(`site/${route}/index.html`), 'text/html')
    const main = doc.querySelector('main')!
    // The school hero precedes <main> in the approved layout.
    const intro = route === 'educators'
      ? main.querySelector('.page-head .lede')!
      : doc.querySelector('.classical-hero-copy > p:not(.classical-kicker)')!
    expect(intro.textContent).toContain('K–8')
    expect(intro.textContent).toContain('5–15')
    expect(intro.textContent).toMatch(/parent|famil|educator|adult/i)
    expect(main.querySelector('.audience-evidence-links a[href="/bede/tour/"]')).not.toBeNull()
    expect(main.querySelector('.audience-evidence-links a[href="/research/"]')).not.toBeNull()
    expect(doc.querySelector('meta[property="og:title"]')!.getAttribute('content')).toBe(
      doc.querySelector('title')!.textContent,
    )
    expect(doc.querySelector('meta[property="og:description"]')!.getAttribute('content')).toBe(
      doc.querySelector('meta[name="description"]')!.getAttribute('content'),
    )
    expect(doc.querySelector('meta[property="og:url"]')!.getAttribute('content')).toBe(
      doc.querySelector('link[rel="canonical"]')!.getAttribute('href'),
    )
  })

  it('offers firsthand feedback while distinguishing teaching research from Bede trials', () => {
    expect(read('site/llms.txt')).toContain('learners ages 5–15')
    const doc = new DOMParser().parseFromString(read('site/research/index.html'), 'text/html')
    const section = doc.querySelector('[aria-labelledby="family-practice"]')!
    expect(section.querySelector('a[href="/bede/tour/"]')).not.toBeNull()
    expect(section.querySelector('a[href="/survey/"]')).not.toBeNull()
    expect(section.textContent).toContain('studies above examine teaching methods and other tools')
    const guide = read('docs/SEARCH_VISIBILITY.md')
    expect(guide).toContain('There is no verified Google indexing result to report yet')
    expect(guide).toContain('Obtain explicit permission')
    expect(guide).toContain('Do not invent them')
  })
})
