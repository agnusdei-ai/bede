/**
 * Printing a teacher's approved plan on its own sheet.
 *
 * The pilot's "Print teacher material" button used to call the page's own
 * print(), which printed the whole teacher screen: every form, every other
 * record and the buttons, with the plan somewhere in the middle. This builds
 * one sheet that holds only the plan and prints it through printHtml, the
 * same way a quiz or a worksheet is printed (utils/printDocument.ts), so
 * nothing else on the screen reaches the paper.
 *
 * Every string is escaped here. Nothing on the sheet is a score, and the
 * sheet says so.
 */
import { escapeHtml, printHtml } from './printDocument'

export interface TeacherPlanSheet {
  /** The sheet's heading, e.g. "Teacher instructional plan". */
  title: string
  learnerName: string
  /** e.g. "Approved by the teacher on 2026-11-15" or "Edited and approved …". */
  approvalLine: string
  /** The plan the teacher approved or wrote, shown exactly as recorded. */
  planText: string
  /** What the plan rests on, one line each. Omitted when there is none. */
  basedOn?: string[]
  /** Said plainly on the sheet: what this is not. */
  disclaimer: string
}

/** Ruled lines for the teacher's own notes after the lesson. */
export const NOTE_LINES = 6

const STYLE = `
:host { all: initial; display: block; }
.sheet { font-family: Georgia, 'Times New Roman', serif; font-size: 12pt; line-height: 1.45; color: #1d2433; background: #fff; -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
.sheet h1 { font-size: 17pt; line-height: 1.25; margin: 0 0 0.3em; font-weight: bold; }
.sheet h2 { font-size: 12pt; margin: 1.1em 0 0.3em; font-weight: bold; }
.meta { font-size: 10.5pt; color: #333; margin: 0 0 0.2em; overflow-wrap: anywhere; }
.plan { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
ul.basis { margin: 0; padding-left: 1.2em; }
ul.basis li { margin: 0 0 0.15em; overflow-wrap: anywhere; font-size: 10.5pt; }
.line { border-bottom: 1px solid #888; height: 1.9em; }
.notes { break-inside: avoid; page-break-inside: avoid; }
.disclaimer { margin-top: 1.4em; padding-top: 0.5em; border-top: 1px solid #999; font-size: 9.5pt; color: #333; overflow-wrap: anywhere; }
`

export function buildTeacherPlanHtml(sheet: TeacherPlanSheet): string {
  const basis = (sheet.basedOn ?? []).filter((line) => line.trim())
  const basisHtml = basis.length
    ? `<h2>Based on</h2><ul class="basis">${basis.map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`
    : ''
  return `<!doctype html><html><head><meta charset="utf-8">`
    + `<title>${escapeHtml(sheet.title)}</title><style>${STYLE}</style></head><body><div class="sheet">`
    + `<h1>${escapeHtml(sheet.title)}</h1>`
    + `<p class="meta">Learner: ${escapeHtml(sheet.learnerName)}</p>`
    + `<p class="meta">${escapeHtml(sheet.approvalLine)}</p>`
    + `<h2>Plan</h2><p class="plan">${escapeHtml(sheet.planText)}</p>`
    + basisHtml
    + `<div class="notes"><h2>Teacher's notes after the lesson</h2>${'<div class="line"></div>'.repeat(NOTE_LINES)}</div>`
    + `<p class="disclaimer">${escapeHtml(sheet.disclaimer)}</p>`
    + `</div></body></html>`
}

/** Print the plan alone. Resolves false if the browser would not print. */
export function printTeacherPlan(sheet: TeacherPlanSheet): Promise<boolean> {
  return printHtml(buildTeacherPlanHtml(sheet))
}
