import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const site = resolve(import.meta.dirname, '../../site')

describe('public crawler access and Bede application schema', () => {
  it('ships a concise Markdown summary with the main public resources', () => {
    const summary = readFileSync(resolve(site, 'llms.txt'), 'utf8')
    expect(summary).toMatch(/^# Bede by Agnus Dei\n\n> /)
    expect(summary.trim().split(/\s+/).length).toBeLessThan(450)
    for (const route of [
      '/', '/homeschool/', '/educators/', '/schools/',
      '/bede/tour/', '/bede/', '/faq/', '/privacy/', '/research/', '/inquire/',
    ]) expect(summary).toContain(`](https://agnusdei.ai${route})`)
    expect(summary).toContain('The public demo is cloud-hosted.')
    expect(summary).toContain('local-only privacy applies to offline installations')
    expect(summary).toContain('School demonstrations are teacher-directed and use synthetic data')
    expect(summary).toContain('bede@agnusdei.ai')
    expect(summary).toContain('info@agnusdei.ai')
    const build = readFileSync(resolve(site, '../scripts/build_pages_site.sh'), 'utf8')
    expect(build).toContain('cp -r site/* publish/')
  })

  it('explicitly allows the requested crawlers and retains the sitemap', () => {
    const robots = readFileSync(resolve(site, 'robots.txt'), 'utf8')
    const groups = robots
      .replace(/#[^\n]*/g, '')
      .trim()
      .split(/\n\s*\n/)
    for (const agent of ['Google-Extended', 'GPTBot', 'Bingbot', '*']) {
      const group = groups.find(group => group.split('\n').some(line =>
        line.trim().toLowerCase() === `user-agent: ${agent}`.toLowerCase(),
      ))
      expect(group, `Missing crawler group: ${agent}`).toBeDefined()
      expect(group).toMatch(/^Allow: \/$/m)
      expect(group).not.toMatch(/^Disallow:\s*\//m)
    }
    expect(robots).toContain('Sitemap: https://agnusdei.ai/sitemap.xml')
  })

  it('includes the requested schema in static HTML without duplicate application entities', () => {
    const html = readFileSync(resolve(site, 'index.html'), 'utf8')
    const scripts = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
    expect(scripts).toHaveLength(1)
    const schema = JSON.parse(scripts[0][1])
    expect(schema['@context']).toBe('https://schema.org')
    const apps = schema['@graph'].filter((node: Record<string, unknown>) =>
      node['@type'] === 'SoftwareApplication',
    )
    expect(apps).toHaveLength(1)
    expect(apps[0]).toMatchObject({
      '@type': 'SoftwareApplication',
      name: 'Bede by Agnus Dei',
      applicationCategory: 'EducationalApplication',
      operatingSystem: 'Linux, macOS, Windows (Containerized / Local-First)',
      description: 'Classical education platform-as-a-service providing Socratic AI tutoring, air-gapped data privacy, and curriculum-aligned inquiry for charter schools and homeschool pods.',
      publisher: { '@id': 'https://agnusdei.ai/#org' },
      url: 'https://agnusdei.ai/',
    })
    expect(schema['@graph'].some((node: Record<string, unknown>) =>
      node['@type'] === 'Organization' && node['@id'] === apps[0].publisher['@id'],
    )).toBe(true)
  })
})
