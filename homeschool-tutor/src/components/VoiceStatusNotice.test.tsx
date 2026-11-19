import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import '../i18n'
import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import VoiceStatusNotice from './VoiceStatusNotice'

const answer = (body: unknown, status = 200) =>
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: status === 200, status, json: async () => body }))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); void i18n.changeLanguage('en') })

describe('VoiceStatusNotice', () => {
  it.each([
    [{ configured: true, where: 'local' }, 'local'],
    [{ configured: true, where: 'cloud' }, 'cloud'],
    [{ configured: false, where: null }, 'none'],
    [{ configured: true, where: 'local', available: false }, 'down'],
    [{ configured: true, where: 'local', available: true }, 'local'],
  ] as const)('explains where Bede speaks: %o', async (body, key) => {
    answer(body)
    render(<VoiceStatusNotice token="tok" />)
    const card = await screen.findByTestId('voice-status')
    expect(card.dataset.voice).toBe(key)
    expect(card.textContent).toContain(en.voiceStatus[key].what)
    expect(card.textContent).toContain(en.voiceStatus[key].next)
    expect(fetch).toHaveBeenCalledWith('/api/tutor/voice', expect.anything())
  })

  it.each([
    [{ configured: false, where: null }],
    [{ configured: true, where: 'local', available: false }],
  ])('tells a parent Bede goes on without speaking and never uses another voice: %o', async (body) => {
    answer(body)
    render(<VoiceStatusNotice token="tok" />)
    const text = (await screen.findByTestId('voice-status')).textContent ?? ''
    expect(text).toMatch(/never uses another voice/)
    expect(text).toMatch(/on screen/)
  })

  it('shows nothing when the status cannot be read', async () => {
    answer({}, 404)
    const { container } = render(<VoiceStatusNotice token="tok" />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('has every line in Spanish too', () => {
    expect(es.voiceStatus.title).not.toBe(en.voiceStatus.title)
    for (const k of ['local', 'cloud', 'none', 'down'] as const) {
      for (const part of ['what', 'next'] as const) {
        expect(es.voiceStatus[k][part]).toBeTruthy()
        expect(es.voiceStatus[k][part]).not.toBe(en.voiceStatus[k][part])
      }
    }
  })

  it('"not set up" and "not answering right now" read differently, each with its own next step', () => {
    expect(en.voiceStatus.none.what).not.toBe(en.voiceStatus.down.what)
    expect(en.voiceStatus.none.next).toMatch(/voice setup guide/)
    expect(en.voiceStatus.down.next).toMatch(/checks again/)
  })
})
