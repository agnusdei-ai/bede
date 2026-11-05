import { describe, expect, it } from 'vitest'
import * as demo from './uploadParts'
import * as app from '../../homeschool-tutor/src/utils/uploadParts'

const f = (mb: number) => ({ size: mb * 1024 * 1024 })

describe('splitting a long upload into parts', () => {
  it('keeps every file, in order, with no limit on how many', () => {
    const files = Array.from({ length: 40 }, () => f(1))
    const parts = demo.splitIntoParts(files)
    expect(parts.flat()).toEqual(files)
    expect(parts.every((p) => p.length <= demo.PART_MAX_FILES)).toBe(true)
  })

  it('keeps a part under the request size, so nginx never refuses it', () => {
    const parts = demo.splitIntoParts([f(5), f(5), f(1), f(6), f(0.5)])
    expect(parts.map((p) => p.length)).toEqual([1, 2, 2])
    // base64 adds a third; the product's nginx accepts 12 MB.
    expect(demo.PART_MAX_BYTES * 4 / 3).toBeLessThan(12 * 1024 * 1024)
  })

  it('matches the app copy exactly', () => {
    expect(demo.PART_MAX_FILES).toBe(app.PART_MAX_FILES)
    expect(demo.PART_MAX_BYTES).toBe(app.PART_MAX_BYTES)
    const files = [f(3), f(3), f(3), f(0.1), f(0.1), f(0.1), f(0.1), f(0.1), f(0.1), f(6)]
    expect(demo.splitIntoParts(files)).toEqual(app.splitIntoParts(files))
  })
})
