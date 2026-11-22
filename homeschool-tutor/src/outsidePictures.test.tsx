/**
 * Outside pictures (Wikipedia and Wikimedia Commons) are for Bede's
 * picture study in History & Geography and Art & Music only: the picture-study
 * card, and the quiz "image" diagram the server allows only in those subjects
 * (homeschool-api/services/practice/diagrams.py IMAGE_SUBJECTS). Ordinary
 * practice pictures are drawn in the app and never fetch anything.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Diagram, { Picture } from './components/Diagram'

const OUTSIDE = /wikipedia\.org|wikimedia\.org|WIKI_SUMMARY|lookupImage\(/
const SRC = resolve(__dirname)
const DEMO = resolve(__dirname, '../../demo/src')

/** The only places that may reach an outside picture. */
const ALLOWED = new Set([
  'components/VisualAidCard.tsx', // picture study
  'components/Diagram.tsx', // the "image" diagram, gated by subject on the server
  'VisualAidCard.tsx',
  'Diagram.tsx',
])

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (name === 'node_modules' || name === 'i18n') return []
    if (statSync(path).isDirectory()) return files(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : []
  })
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('outside pictures', () => {
  it('are reached only from the picture-study card and the gated image diagram, in the app and the demo', () => {
    for (const root of [SRC, DEMO]) {
      const reaching = files(root)
        .filter((file) => OUTSIDE.test(readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/[^\n]*/g, '$1')))
        .map((file) => relative(root, file))
      expect(reaching.filter((file) => !ALLOWED.has(file))).toEqual([])
    }
  })

  it('in Diagram.tsx only the image diagram reaches the lookup, never a practice picture', () => {
    const source = readFileSync(join(SRC, 'components/Diagram.tsx'), 'utf8')
    const picture = source.slice(source.indexOf('export function Picture('), source.indexOf('export const DRAWINGS'))
    const svgPicture = source.slice(source.indexOf('function SvgPicture('), source.indexOf('function Scene('))
    for (const body of [picture, svgPicture]) {
      expect(body.length).toBeGreaterThan(50)
      expect(OUTSIDE.test(body)).toBe(false)
      expect(body).not.toMatch(/<img|fetch\(/)
    }
  })

  it('a practice picture and a pictures diagram fetch nothing when shown', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<>
      <Picture name="fox" label="fox" size="h-20 w-20" />
      <Diagram d={{ kind: 'pictures', groups: [{ icon: 'apple', count: 3 }] }} />
      <Diagram d={{ kind: 'scene', icon: 'dog', action: 'running' }} />
    </>)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(document.querySelector('img')).toBeNull()
  })
})
