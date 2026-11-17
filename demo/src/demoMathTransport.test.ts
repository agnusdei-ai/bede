import { afterEach, describe, expect, it, vi } from 'vitest'

describe('demo Number Time transport', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('loads the selected topic through the demo-only endpoint', async () => {
    vi.stubEnv('VITE_DEMO_API_BASE', 'https://api.example.test/')
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      level: '1', topic: 'add', demo: true, recorded: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { demoMathTransport } = await import('./api')

    const lesson = await demoMathTransport('session-token').load(false, 'add')

    expect(lesson).toMatchObject({ level: '1', topic: 'add', demo: true, recorded: false })
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/k2-practice/demo/math/lesson?topic=add',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: ['Bearer', 'session-token'].join(' ') }),
      }),
    )
  })

  it('submits one answer with its retry id through the demo-only endpoint', async () => {
    vi.stubEnv('VITE_DEMO_API_BASE', 'https://api.example.test')
    vi.resetModules()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      correct: true, understood: true, demo: true, recorded: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { demoMathTransport } = await import('./api')

    const result = await demoMathTransport('session-token').answer(
      'signed/lesson', 'your_turn', 2, '7', 'submission_000001',
    )

    expect(result).toMatchObject({ correct: true, demo: true, recorded: false })
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/k2-practice/demo/math/lessons/signed%2Flesson/answers',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: ['Bearer', 'session-token'].join(' ') }),
        body: JSON.stringify({
          phase: 'your_turn', index: 2, choice: '7', submission_id: 'submission_000001',
        }),
      }),
    )
  })
})
