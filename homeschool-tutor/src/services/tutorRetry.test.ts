/**
 * A dropped connection must not cost a child their turn.
 *
 * From a real 5G trace, mid-lesson: `POST /tutor/chat` rejected with
 * `TypeError: Load failed` after 12.9 seconds, the child's answer was
 * discarded, and the only thing that spoke afterwards was the 60-second
 * idle timer sending [CONTINUE] — which invites them to go on as though
 * they had never answered. Nothing retried.
 *
 * These guards pin the retry AND the three things it must refuse to do,
 * because an over-eager retry is its own bug: a duplicated model call, a
 * sentence restarted under a reader mid-way through it, or a request
 * reissued for a child who has already left.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat } from './api'
import type { SessionConfig, StreamChunk, Subject } from '../types'

const CONFIG = { student_name: 'Ada', grade: '4', subjects: [] } as unknown as SessionConfig
const SUBJECT = 'mathematics' as Subject

/** A Response whose body streams these already-encoded SSE lines. */
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

/** Safari's own wording for a transport failure — the reported case. */
function loadFailed() {
  return new TypeError('Load failed')
}

async function collect(gen: AsyncGenerator<StreamChunk>): Promise<StreamChunk[]> {
  const out: StreamChunk[] = []
  for await (const c of gen) out.push(c)
  return out
}

function run(signal?: AbortSignal) {
  return streamTutorChat('tok', CONFIG, SUBJECT, [], 'I was coughing the whole day', signal)
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
  it('retries, and the child gets the reply they would have lost', async () => {
    fetchMock
      .mockRejectedValueOnce(loadFailed())
      .mockResolvedValueOnce(sseResponse(REPLY))

    const chunks = await collect(run())

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
  })

  it('sends the child’s own words again, not an empty turn', async () => {
    // The retry must reissue the SAME message. A retry that dropped the
    // child's text would produce a reply to nothing, which is the exact
    // failure the idle [CONTINUE] sentinel already causes.
    fetchMock
      .mockRejectedValueOnce(loadFailed())
      .mockResolvedValueOnce(sseResponse(REPLY))

    await collect(run())

    const bodies = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body))
    expect(bodies).toHaveLength(2)
    expect(bodies[0].child_message).toBe('I was coughing the whole day')
    expect(bodies[1]).toEqual(bodies[0])
  })

  it('gives up rather than retrying forever, and reports the real failure', async () => {
    fetchMock.mockRejectedValue(loadFailed())

    await expect(collect(run())).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('what it deliberately will not retry', () => {
  it('leaves a refusal the server actually made alone', async () => {
    // A 4xx/5xx is a decision, not a dropped packet. Repeating it just
    // asks to be refused twice and spends a family's tokens doing it.
    fetchMock.mockResolvedValue(sseResponse([], false, 500))

    await expect(collect(run())).rejects.toThrow(/Tutor request failed/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not restart a reply the child is already reading', async () => {
    // Fails AFTER the first chunk reached the caller. Retrying here would
    // replay text already on screen, mid-sentence.
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

  it('does not reissue a request for a child who has already left', async () => {
    const controller = new AbortController()
    fetchMock.mockImplementation(async () => {
      controller.abort()
      throw loadFailed()
    })

    await expect(collect(run(controller.signal))).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
