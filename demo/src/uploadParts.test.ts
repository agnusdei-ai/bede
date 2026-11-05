import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

  it('keeps a part under the request size, so nginx and the API never refuse it', () => {
    const parts = demo.splitIntoParts([f(20), f(20), f(3), f(1), f(25), f(0.5)])
    expect(parts.map((p) => p.length)).toEqual([1, 3, 1, 1])
    // A part is at most one 25 MB file or 24 MB of files: base64 adds a third,
    // nginx accepts 42 MB on /api/practice/, the API 30 MB a request.
    expect(demo.FILE_MAX_BYTES * 4 / 3).toBeLessThan(42 * 1024 * 1024)
    expect(Math.max(demo.FILE_MAX_BYTES, demo.PART_MAX_BYTES)).toBeLessThanOrEqual(30 * 1024 * 1024)
  })

  it('accepts up to 1 GB in all and 25 MB a file', () => {
    expect(demo.uploadProblem(Array.from({ length: 40 }, () => f(25)))).toBeNull()
    expect(demo.uploadProblem(Array.from({ length: 41 }, () => f(25)))).toBe('total')
    expect(demo.uploadProblem([f(25.1)])).toBe('file')
    expect(demo.UPLOAD_MAX_BYTES).toBe(1024 ** 3)
  })

  it('matches the app copy exactly', () => {
    expect(demo.PART_MAX_FILES).toBe(app.PART_MAX_FILES)
    expect(demo.PART_MAX_BYTES).toBe(app.PART_MAX_BYTES)
    expect(demo.FILE_MAX_BYTES).toBe(app.FILE_MAX_BYTES)
    expect(demo.UPLOAD_MAX_BYTES).toBe(app.UPLOAD_MAX_BYTES)
    expect(demo.SOURCE_TEXT_MAX_CHARS).toBe(app.SOURCE_TEXT_MAX_CHARS)
    const files = [f(3), f(3), f(3), f(0.1), f(0.1), f(0.1), f(0.1), f(0.1), f(0.1), f(6)]
    expect(demo.splitIntoParts(files)).toEqual(app.splitIntoParts(files))
  })
})

describe('the browser and the API agree on the limits', () => {
  const py = (path: string) => readFileSync(resolve(__dirname, '../../homeschool-api', path), 'utf8')
  const mb = (src: string, name: string) => {
    const m = src.match(new RegExp(`^${name} = (\\d+) \\* 1024 \\* 1024`, 'm'))
    if (!m) throw new Error(`${name} not found`)
    return Number(m[1]) * 1024 * 1024
  }
  it('per file, per request and for copied-out source text', () => {
    const safety = py('services/practice/upload_safety.py')
    expect(demo.FILE_MAX_BYTES).toBe(mb(safety, 'MAX_PAGE_BYTES'))
    expect(demo.PART_MAX_BYTES).toBeLessThanOrEqual(mb(safety, 'MAX_REQUEST_BYTES'))
    expect(demo.FILE_MAX_BYTES).toBeLessThanOrEqual(mb(safety, 'MAX_REQUEST_BYTES'))
    const model = py('models/practice.py').match(/^MAX_SOURCE_PAGES_TEXT = ([\d_]+)/m)
    expect(Number(model?.[1].replace(/_/g, ''))).toBe(demo.SOURCE_TEXT_MAX_CHARS)
    const nginx = readFileSync(resolve(__dirname, '../../homeschool-tutor/nginx.conf'), 'utf8')
    const practice = nginx.match(/location \/api\/practice\/ \{\s*client_max_body_size (\d+)m;/)
    expect(Number(practice?.[1]) * 1024 * 1024).toBeGreaterThan(demo.FILE_MAX_BYTES * 4 / 3)
  })
})
