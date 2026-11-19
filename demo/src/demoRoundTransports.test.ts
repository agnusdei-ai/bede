import { afterEach, describe, expect, it, vi } from 'vitest'

function ok(body: unknown) {
  return vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }))
}

describe('demo Sound Time and Map Practice transports', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('loads and answers Sound Time through the demo-only endpoints', async () => {
    vi.stubEnv('VITE_DEMO_API_BASE', 'https://api.example.test')
    vi.resetModules()
    const fetchMock = ok({ lesson_id: 'L1', demo: true, recorded: false })
    vi.stubGlobal('fetch', fetchMock)
    const { demoPhonicsTransport } = await import('./api')
    const transport = demoPhonicsTransport('session-token')

    await transport.load(true)
    await transport.answer('a/b', 'together', 0, 'bus')

    expect(fetchMock).toHaveBeenNthCalledWith(1,
      'https://api.example.test/k2-practice/demo/phonics/lesson?audio=true',
      expect.objectContaining({ method: 'GET' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      'https://api.example.test/k2-practice/demo/phonics/lessons/a%2Fb/answers',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: ['Bearer', 'session-token'].join(' ') }),
        body: JSON.stringify({ phase: 'together', index: 0, choice: 'bus' }),
      }))
  })

  it('sends a tapped map square or a chosen answer, never both', async () => {
    vi.stubEnv('VITE_DEMO_API_BASE', 'https://api.example.test')
    vi.resetModules()
    const fetchMock = ok({ correct: true, understood: true, demo: true, recorded: false })
    vi.stubGlobal('fetch', fetchMock)
    const { demoMapTransport } = await import('./api')
    const transport = demoMapTransport('session-token')

    await transport.load()
    await transport.answer('L2', 'your_turn', 1, { cell: [2, 3] })
    await transport.answer('L2', 'your_turn', 2, { choice: 'water' })

    expect(fetchMock.mock.calls[0][0]).toBe('https://api.example.test/k2-practice/demo/maps/lesson')
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ phase: 'your_turn', index: 1, cell: [2, 3] }))
    expect(fetchMock.mock.calls[2][1].body).toBe(JSON.stringify({ phase: 'your_turn', index: 2, choice: 'water' }))
  })
})
