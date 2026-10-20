import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const root = join(__dirname, '../..')
function marketingFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? marketingFiles(path) : [path]
  })
}

describe('school marketing affiliation boundaries', () => {
  it.each([
    ...marketingFiles(join(root, 'site')).filter(path => /\.(html|js|json|txt|xml|css|svg)$/i.test(path)),
    join(root, 'demo/public/launch.html'),
  ])('does not name an uncontracted school in %s', path => {
    expect(readFileSync(path, 'utf8')).not.toMatch(/\bvalor\b/i)
  })

  it('does not turn a synthetic demonstration into a claimed customer pilot', () => {
    const school = readFileSync(join(root, 'site/schools/index.html'), 'utf8')
    const launch = readFileSync(join(root, 'demo/public/launch.html'), 'utf8')
    for (const text of [school, launch]) {
      expect(text).toContain('No customer agreement, school endorsement, or approved deployment is implied.')
      expect(text).toContain('synthetic')
      expect(text).not.toMatch(/current.*?(?:customer|campus) pilot/i)
    }
    expect(school).toContain('school evaluation requires its own signed scope')
  })
})
