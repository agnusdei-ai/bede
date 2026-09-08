/**
 * The demo runs the product's network resilience, not a copy of it.
 *
 * The trace this was written from IS a demo trace (bede-demo-api.onrender.com
 * over 5G), so the demo is the surface where a dropped turn was actually
 * seen — and it is the one a prospective family judges Bede by. The same
 * four properties the app's own `services/tutorRetry.test.ts` pins are
 * asserted here against the demo's own streamTutorChat.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat } from './api'
import type { SessionConfig, StreamChunk, Subject } from './api'

const CONFIG = { student_name: 'Guest', grade: '4', subjects: [] } as unknown as SessionConfig
const SUBJECT = 'mathematics' as Subject

function sseResponse(lines: string[], ok = true, status = 200): Response {
  let i = 0
  const encoder = new TextEncoder()
  return {
    ok,
    status,
    body: {
      getReader: () => ({
        read: async () =>
          i < lines.length
            ? { done: false, value: encoder.encode(lines[i++]) }
            : { done: true, value: undefined },
        cancel: async () => {},
      }),
    },
  } as unknown as Response
}

const REPLY = [
  'data: {"type":"text","content":"Tell me what you remember."}\n',
  'data: {"type":"done"}\n',
]

const loadFailed = () => new TypeError('Load failed')

async function collect(gen: AsyncGenerator<StreamChunk>): Promise<StreamChunk[]> {
  const out: StreamChunk[] = []
  for await (const c of gen) out.push(c)
  return out
}

function run(signal?: AbortSignal) {
  return streamTutorChat('tok', CONFIG, SUBJECT, [], 'I was coughing the whole day', null, signal)
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('a connection that drops before Bede answers', () => {
  it('retries, and the visitor gets the reply they would have lost', async () => {
    fetchMock.mockRejectedValueOnce(loadFailed()).mockResolvedValueOnce(sseResponse(REPLY))
    const chunks = await collect(run())
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
  })

  it('gives up rather than retrying forever', async () => {
    fetchMock.mockRejectedValue(loadFailed())
    await expect(collect(run())).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('what it deliberately will not retry', () => {
  it('leaves a refusal the server actually made alone', async () => {
    fetchMock.mockResolvedValue(sseResponse([], false, 500))
    await expect(collect(run())).rejects.toThrow(/Tutor request failed/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('never retries an ended trial session, however the connection behaved', async () => {
    // A 401 here means the demo code expired. Retrying it would spend two
    // more round trips to be told the same thing, and delay the visitor
    // reaching the screen that actually helps them (generate a new code).
    fetchMock.mockResolvedValue(sseResponse([], false, 401))
    await expect(collect(run())).rejects.toThrow(/session has ended/i)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not restart a reply the visitor is already reading', async () => {
    const encoder = new TextEncoder()
    let read = 0
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (read++ === 0) {
              return { done: false, value: encoder.encode('data: {"type":"text","content":"Well"}\n') }
            }
            throw loadFailed()
          },
          cancel: async () => {},
        }),
      },
    } as unknown as Response)

    const seen: StreamChunk[] = []
    await expect(
      (async () => {
        for await (const c of run()) seen.push(c)
      })(),
    ).rejects.toThrow('Load failed')
    expect(seen).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not reissue a request for a visitor who has already left', async () => {
    const controller = new AbortController()
    fetchMock.mockImplementation(async () => {
      controller.abort()
      throw loadFailed()
    })
    await expect(collect(run(controller.signal))).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
