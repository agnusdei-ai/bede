/**
 * The one automated logout that is NOT covered by a behavioural test, and an
 * honest account of what this file does instead.
 *
 * Three of the four automated logouts are driven end to end elsewhere:
 * AppShell's idle and token-rejected paths in guards/AppShell.test.tsx, and
 * the 401 interceptor in components/GlobalAuthInterceptor.test.tsx. The
 * fourth — TutorSession's break-inactivity logout — fires only from inside a
 * fully rendered tutoring session with a live config, a running clock and a
 * mounted chat, and standing all of that up in jsdom to assert one string
 * would be a large, brittle harness for a small fact.
 *
 * WHAT THIS TEST IS. A structural check that the call site still records the
 * right reason. It catches the two mutations that actually happened when
 * this was probed: deleting the call, and pointing it at the generic
 * 'inactivity' wording instead of the break-specific one.
 *
 * WHAT IT IS NOT. Proof that the branch runs, or that it runs at the right
 * moment. Reading source is not executing it. If TutorSession's break
 * handling ever becomes reachable in a test without the full component, this
 * file should be replaced by that test rather than kept alongside it.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { LOGOUT_NOTICE_KEYS, type LogoutReason } from './logoutNotice'

const TUTOR_SESSION = readFileSync(
  join(__dirname, '../pages/TutorSession.tsx'),
  'utf8',
)

describe('the break-inactivity logout still explains itself', () => {
  it('records a reason before signing the child out', () => {
    expect(TUTOR_SESSION).toContain("setLogoutNotice('break-inactivity')")
  })

  it('uses the break-specific reason, not the generic one', () => {
    // A child who walked away from a break they were TOLD to take should be
    // told that, not accused of being idle. docs/CHILD_GUIDE.md promises
    // them this rule in those terms.
    expect(TUTOR_SESSION).not.toContain("setLogoutNotice('inactivity')")
  })

  it('records it inside the break branch, not somewhere else in the file', () => {
    const branch = TUTOR_SESSION.slice(
      TUTOR_SESSION.indexOf('BREAK_INACTIVITY_LOGOUT_MS) {'),
    ).slice(0, 600)
    expect(branch).toContain("setLogoutNotice('break-inactivity')")
    expect(branch.indexOf("setLogoutNotice('break-inactivity')"))
      .toBeLessThan(branch.indexOf('logout()'))
  })
})

describe('every reason this app can record is one the UI can render', () => {
  it('has no reason without an i18n key', () => {
    const reasons = Object.keys(LOGOUT_NOTICE_KEYS) as LogoutReason[]
    for (const reason of reasons) {
      expect(LOGOUT_NOTICE_KEYS[reason]).toMatch(/^common\.loggedOut/)
    }
  })
})
