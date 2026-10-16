import { describe, expect, it } from 'vitest'
import { useSessionStore } from './sessionStore'
import type { SessionConfig } from '../types'

const config = { student_name: 'Example Learner', grade: '1', grade_stage: 'K-2',
  subjects: ['mathematics'] } as unknown as SessionConfig

describe('pilot session id', () => {
  it('is set by startPilotSession and starts the session', () => {
    useSessionStore.getState().startPilotSession(config, 'launch-1')
    const s = useSessionStore.getState()
    expect(s.pilotSessionId).toBe('launch-1')
    expect(s.sessionId).not.toBeNull()
    expect(s.currentSubject).toBe('mathematics')
  })

  it('is cleared by any ordinary setSessionConfig, so it cannot ride into another session', () => {
    useSessionStore.getState().startPilotSession(config, 'launch-1')
    useSessionStore.getState().setSessionConfig({ ...config, student_name: 'Household Child' })
    expect(useSessionStore.getState().pilotSessionId).toBeNull()
  })

  it('is cleared on logout', () => {
    useSessionStore.getState().startPilotSession(config, 'launch-1')
    useSessionStore.getState().logout()
    expect(useSessionStore.getState().pilotSessionId).toBeNull()
  })
})
