/**
 * The launch page's checkout links ARE the Worker config — checked, not remembered.
 *
 * `demo/public/launch.html` is static HTML served under `script-src 'self'`
 * (site/_headers): no inline-script config point exists, so the two CTA hrefs
 * themselves are the configuration of the storefront origin, marked by an HTML
 * comment as the one place to update. `license-server/wrangler.jsonc` states
 * the same fact independently — a Worker's `name` field is what Cloudflare
 * serves at https://<name>.<account-subdomain>/. The two files live in
 * directories that never conflict in git, which is precisely how this
 * repository has produced drift before (the palette precedent: see
 * homeschool-tutor/src/palette.test.ts). So this is the assertion that fails
 * when they part company: every workers.dev link on the launch page must
 * equal the origin the committed Worker config will actually deploy to.
 *
 * The real defect this pins: the CTAs shipped pointing at
 * `license-server.agnusdei.workers.dev` while the committed Worker is named
 * `bede-license-server` — one prefix, entirely unreachable storefront.
 *
 * The account subdomain is pinned here because wrangler.jsonc cannot carry it
 * (Cloudflare supplies the account subdomain at deploy time); the same
 * subdomain serves the site+demo Worker (root wrangler.jsonc), so it is a
 * workspace constant, not a guess.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO = join(__dirname, '../..')

const WORKERS_DEV_SUBDOMAIN = 'agnusdei.workers.dev'

function workerNameFromWranglerConfig(source: string): string {
  // JSONC: strip // line comments (the (?<!:) lookbehind keeps https:// intact),
  // then read the "name" field — "database_name" cannot match: its key carries
  // a different leading quote.
  const withoutComments = source.replace(/(?<!:)\/\/[^\n]*/g, '')
  const match = withoutComments.match(/"name"\s*:\s*"([^"]+)"/)
  if (!match) throw new Error('license-server/wrangler.jsonc has no "name" field')
  return match[1]
}

function workersDevHrefs(launchPage: string): string[] {
  return [...launchPage.matchAll(/href="(https:\/\/[^"]*?\.workers\.dev\/?)"/g)].map((m) => m[1])
}

describe('launch page checkout links vs license-server Worker config', () => {
  const launchPage = readFileSync(join(REPO, 'demo/public/launch.html'), 'utf8')
  const wranglerConfig = readFileSync(join(REPO, 'license-server/wrangler.jsonc'), 'utf8')
  const expectedOrigin = `https://${workerNameFromWranglerConfig(wranglerConfig)}.${WORKERS_DEV_SUBDOMAIN}/`

  it('parses the Worker name out of the commented wrangler.jsonc', () => {
    expect(workerNameFromWranglerConfig(wranglerConfig)).toBe('bede-license-server')
  })

  it('points every checkout link at the configured storefront origin', () => {
    const hrefs = workersDevHrefs(launchPage)
    expect(
      hrefs.length,
      'launch page must carry at least one checkout link — did the CTA row disappear?',
    ).toBeGreaterThan(0)
    for (const href of hrefs) {
      expect(href, `checkout link drift: ${href}`).toBe(expectedOrigin)
    }
  })
})
