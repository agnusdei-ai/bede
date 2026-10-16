import { describe, expect, it } from 'vitest'
import { ApiRequestError, describeFailure } from './requestFailure'

const ctx = { action: 'save the evidence' }

describe('describeFailure', () => {
  it.each([
    [401, /session has ended\. Sign in again/],
    [403, /don't have permission/],
    [404, /could not be found/],
    [409, /changed this at the same time/],
    [422, /wasn't accepted/],
    [429, /Wait a minute/],
    [500, /server could not finish/],
    [503, /server could not finish/],
  ])('maps status %i to an actionable sentence', (status, expected) => {
    const out = describeFailure(new ApiRequestError(status, 'raw server text'), ctx)
    expect(out.startsWith('Could not save the evidence. ')).toBe(true)
    expect(out).toMatch(expected)
    expect(out).not.toContain('raw server text')
  })

  it('treats a transport failure as a connection problem', () => {
    for (const err of [new TypeError('Load failed'), new Error('Failed to fetch')]) {
      expect(describeFailure(err, ctx)).toMatch(/couldn't reach the server/)
    }
  })

  it('never echoes an unknown error or a stack', () => {
    const err = new Error('Traceback: KeyError at line 12')
    const out = describeFailure(err, ctx)
    expect(out).not.toMatch(/Traceback|KeyError/)
    expect(out).toMatch(/Something went wrong/)
  })

  it("uses the caller's sharper wording where given", () => {
    expect(describeFailure(new ApiRequestError(409, ''), { ...ctx, conflict: 'Decide the draft first.' }))
      .toBe('Could not save the evidence. Decide the draft first.')
  })
})
