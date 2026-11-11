/**
 * One way to print, in both apps.
 *
 * Quizzes, answer keys and practice worksheets print through the same page
 * builder and the same hidden iframe in the demo and in the product, so a
 * parent trying the demo on a phone prints what a family would. The behaviour
 * is tested in homeschool-tutor/src/utils/printDocument.test.ts; this checks
 * the two copies are the same file, byte for byte.
 *
 * It reads the app's copy as text rather than importing it: the demo's CI
 * does not install the app's dependencies, and importing across apps is what
 * breaks the demo's type-check.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { buildPrintHtml } from './printDocument'

const demoCopy = readFileSync(join(__dirname, 'printDocument.ts'), 'utf8')
const appCopy = readFileSync(join(__dirname, '../../homeschool-tutor/src/utils/printDocument.ts'), 'utf8')

describe('printDocument', () => {
  it('is the same file in the demo and the app', () => {
    expect(demoCopy).toBe(appCopy)
  })

  it('imports nothing, so the copy stays safe to mirror', () => {
    expect(demoCopy).not.toMatch(/^import /m)
  })

  it('builds a student copy with name and date lines in the demo too', () => {
    const html = buildPrintHtml({
      title: 'Quiz',
      labels: { name: 'Name', date: 'Date', keyTitle: 'Quiz: answer key' },
      copies: ['student'],
      items: [{ prompt: '<b>2 + 2</b>', answer: '4' }],
    })
    expect(html).toContain('Name <span class="fill">')
    expect(html).toContain('&lt;b&gt;2 + 2&lt;/b&gt;')
    expect(html).not.toContain('class="ans"')
  })
})
