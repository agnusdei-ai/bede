/**
 * The teacher's printed plan holds the plan and nothing else from the
 * screen, escapes everything a teacher typed, and always carries the line
 * saying it is not an official score.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINT_ROOT_ID, clearPrintSheet } from './printDocument'
import { NOTE_LINES, buildTeacherPlanHtml, printTeacherPlan } from './printTeacherPlan'

const sheet = {
  title: 'Teacher instructional plan',
  learnerName: 'Sample Learner One',
  approvalLine: 'Approved by the teacher on 2026-11-15',
  planText: 'Sound boxes, ten minutes.\nSecond line <script>alert(1)</script> & "more"',
  basedOn: ['Phonemic Segmentation Fluency (PSF), 2026-11-10: the source report lists intensive support (at risk).', '  '],
  disclaimer: 'Teacher-use plan only. Not an official DIBELS score or assessment report.',
}

afterEach(() => { clearPrintSheet(); vi.restoreAllMocks() })

describe('the printed teacher plan', () => {
  it('escapes what the teacher typed', () => {
    const html = buildTeacherPlanHtml(sheet)
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;more&quot;')
  })

  it('carries the plan, its basis, room for notes and the not-a-score line', () => {
    const doc = new DOMParser().parseFromString(buildTeacherPlanHtml(sheet), 'text/html')
    expect(doc.querySelector('.plan')?.textContent).toBe(sheet.planText)
    expect(doc.querySelectorAll('ul.basis li').length).toBe(1) // the blank line is dropped
    expect(doc.querySelectorAll('.notes .line').length).toBe(NOTE_LINES)
    expect(doc.querySelector('.disclaimer')?.textContent).toBe(sheet.disclaimer)
    expect(doc.body.textContent).toContain('Sample Learner One')
  })

  it('leaves out the basis heading when there is none', () => {
    expect(buildTeacherPlanHtml({ ...sheet, basedOn: undefined })).not.toContain('Based on')
  })

  it('prints only the sheet: everything else on the page is hidden for print', async () => {
    document.body.innerHTML = '<main id="screen">another learner\'s record</main>'
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    expect(await printTeacherPlan(sheet)).toBe(true)
    expect(print).toHaveBeenCalledTimes(1)
    const host = document.getElementById(PRINT_ROOT_ID)!
    expect(host.shadowRoot?.querySelector('.plan')?.textContent).toBe(sheet.planText)
    expect(host.shadowRoot?.textContent).not.toContain("another learner's record")
    expect(document.head.textContent).toContain(`body > *:not(#${PRINT_ROOT_ID}) { display: none !important; }`)
  })
})
