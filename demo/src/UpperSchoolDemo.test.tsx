import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchAvailableLocales: vi.fn().mockResolvedValue([]),
  generateDemoCode: vi.fn().mockResolvedValue('123456'),
  loginWithCode: vi.fn().mockResolvedValue({ token: 'demo-test-token' }),
}))
vi.mock('./api', async (original) => ({
  ...await original<typeof import('./api')>(), ...mocks,
}))

import { CodeScreen } from './App'
import { DEMO_GRADES, generateDemoCode } from './api'
import i18n from './i18n'

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  localStorage.setItem('bede-demo-consent-v2', 'true')
})
afterEach(async () => {
  cleanup()
  await i18n.changeLanguage('en')
})

describe.each(['en', 'es'])('interactive upper-school selection in %s', (locale) => {
  it.each(['8', '9', '10', '11', '12'])('starts and remembers the selected Grade %s', async (grade) => {
    await i18n.changeLanguage(locale)
    const onLoggedIn = vi.fn()
    await act(async () => { render(<CodeScreen onLoggedIn={onLoggedIn} />) })
    const selector = document.getElementById('student-grade') as HTMLSelectElement
    expect(Array.from(selector.options).map(o => o.value)).toEqual(['', ...DEMO_GRADES])
    expect(document.getElementById('demo-grade-help')?.textContent).toContain('9–12')
    fireEvent.change(selector, { target: { value: grade } })
    expect(selector.value).toBe(grade)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: i18n.t('codeScreen.generateCode') }))
    })
    await waitFor(() => expect(onLoggedIn).toHaveBeenCalledWith('demo-test-token', '123456'))
    expect(generateDemoCode).toHaveBeenCalledWith('', grade, '', '')
    expect(sessionStorage.getItem('bede-demo-grade')).toBe(grade)
    cleanup()
    await act(async () => { render(<CodeScreen onLoggedIn={vi.fn()} />) })
    expect((document.getElementById('student-grade') as HTMLSelectElement).value).toBe(grade)
  })
})
