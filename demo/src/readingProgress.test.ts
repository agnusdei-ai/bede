import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { newProgressId, overallPercent, watchProgress, withProgress, type ProgressState } from './readingProgress'

afterEach(() => vi.useRealTimers())

describe('reading progress', () => {
  it('counts the whole upload: finished parts in full, the current part by its pages', () => {
    expect(overallPercent(1, 1, { stage: 'checking', done: 0, total: null })).toBe(0)
    expect(overallPercent(1, 1, { stage: 'reading', done: 6, total: 12 })).toBe(48)
    expect(overallPercent(2, 4, { stage: 'reading', done: 3, total: 6 })).toBe(38)
    expect(overallPercent(4, 4, { stage: 'reading', done: 6, total: 6 })).toBe(100)
    expect(overallPercent(1, 1, { stage: 'drafting', done: 0, total: null })).toBe(95)
  })

  it('makes ids the server accepts', () => {
    for (let i = 0; i < 20; i++) expect(newProgressId()).toMatch(/^[A-Za-z0-9-]{8,64}$/)
  })

  it('polls until stopped, and a failed poll changes nothing', async () => {
    vi.useFakeTimers()
    const seen: number[] = []
    let n = 0
    const fetcher = vi.fn(async () => {
      n += 1
      if (n === 2) throw new TypeError('Load failed')
      return n === 3 ? null : { stage: 'reading' as const, done: n, total: 9 }
    })
    const stop = watchProgress(fetcher, 'abcdefgh', (s) => seen.push(s.done), 1000)
    for (let i = 0; i < 4; i++) await vi.advanceTimersByTimeAsync(1000)
    stop()
    await vi.advanceTimersByTimeAsync(5000)
    expect(seen).toEqual([1, 4])
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('runs every part with its own id and never moves backwards', async () => {
    const states: ProgressState[] = []
    const ids: string[] = []
    const results = await withProgress(['a', 'b'], async (part, _i, id) => { ids.push(id); return part.toUpperCase() },
      async () => ({ stage: 'reading', done: 0, total: 6 }), (s) => states.push(s))
    expect(results).toEqual(['A', 'B'])
    expect(new Set(ids).size).toBe(2)
    const percents = states.map((s) => s.percent)
    expect(percents).toEqual([...percents].sort((x, y) => x - y))
    expect(percents.at(-1)).toBe(100)
  })

  it('is the same module as the app copy', () => {
    const strip = (s: string) => s.replace(/ \* Mirror(?:ed)?[\s\S]*?the same\.\n/, '')
    const demo = readFileSync(resolve(__dirname, 'readingProgress.ts'), 'utf8')
    const app = readFileSync(resolve(__dirname, '../../homeschool-tutor/src/utils/readingProgress.ts'), 'utf8')
    expect(strip(demo)).toBe(strip(app))
  })
})
