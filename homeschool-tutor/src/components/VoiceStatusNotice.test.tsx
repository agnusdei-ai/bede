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
  ] as const)('explains where Bede speaks: %o', async (body, key) => {
    answer(body)
    render(<VoiceStatusNotice token="tok" />)
    const card = await screen.findByTestId('voice-status')
    expect(card.dataset.voice).toBe(key)
    expect(card.textContent).toContain(en.voiceStatus[key])
    expect(fetch).toHaveBeenCalledWith('/api/tutor/voice', expect.anything())
  })

  it('tells a parent with no voice that the browser voice is never used', async () => {
    answer({ configured: false, where: null })
    render(<VoiceStatusNotice token="tok" />)
    expect((await screen.findByTestId('voice-status')).textContent).toMatch(/never uses your browser/)
  })

  it('shows nothing when the status cannot be read', async () => {
    answer({}, 404)
    const { container } = render(<VoiceStatusNotice token="tok" />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('has every line in Spanish too', () => {
    for (const k of ['title', 'local', 'cloud', 'none'] as const) {
      expect(es.voiceStatus[k]).toBeTruthy()
      expect(es.voiceStatus[k]).not.toBe(en.voiceStatus[k])
    }
  })
})
