import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '../..')
const launch = readFileSync(join(root, 'demo/public/launch.html'), 'utf8')

describe('launch page email pricing requests', () => {
  it.each(['homeschool', 'coop', 'charter_school'])('offers an explicit %s pricing request', (plan) => {
    document.documentElement.innerHTML = launch
    const link = document.querySelector<HTMLAnchorElement>(
      `a[href="/inquire/?audience=${plan}"]`,
    )
    expect(link).not.toBeNull()
    expect(link!.textContent).toMatch(/request.*pricing/i)
  })

  it('does not publish prices, discounts, trials, or a public checkout shortcut', () => {
    expect(launch).not.toMatch(/\$\s*\d|&#(?:36|x24);|&dollar;|\d+\s*%\s*off|7-day free trial/i)
    expect(launch).not.toMatch(/href="[^"]*(?:workers\.dev|\/checkout|#trial-form)/)
    expect(launch).toContain('provided in response to an email request')
  })

  it('retains the restricted school pilot scope', () => {
    expect(launch).toContain('teacher-directed and synthetic-data-only')
    expect(launch).toContain('no direct student tutoring')
    expect(launch).toContain('institutional, security, and deployment qualification')
  })
})
