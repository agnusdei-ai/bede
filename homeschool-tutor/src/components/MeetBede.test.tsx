import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import MeetBede from './MeetBede'

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

describe('MeetBede', () => {
  it('greets the child by name and lists all four points plus the safety note', () => {
    render(<MeetBede studentName="Emma" gradeStage="K-2" onDone={vi.fn()} />)

    expect(screen.getByText("Hi Emma, I'm Bede!")).toBeTruthy()
    expect(screen.getByText(/press and hold the microphone button/i)).toBeTruthy()
    expect(screen.getByText(/tap the pencil button/i)).toBeTruthy()
    expect(screen.getByText(/break every hour/i)).toBeTruthy()
    expect(screen.getByText(/find your mom or dad/i)).toBeTruthy()
  })

  it('calls onDone when the begin button is pressed', () => {
    const onDone = vi.fn()
    render(<MeetBede studentName="Jack" gradeStage="6-8" onDone={onDone} />)

    fireEvent.click(screen.getByRole('button', { name: "Let's begin!" }))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('renders in Spanish when the active locale is es', async () => {
    await i18n.changeLanguage('es')
    render(<MeetBede studentName="Emma" gradeStage="K-2" onDone={vi.fn()} />)

    expect(screen.getByText('¡Hola Emma, soy Bede!')).toBeTruthy()
    expect(screen.getByRole('button', { name: '¡Empecemos!' })).toBeTruthy()
  })
})
