import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import i18n from './i18n'
import DemoPracticeDelivery from './DemoPracticeDelivery'

afterEach(async () => {
  cleanup()
  await i18n.changeLanguage('en')
})

const item = { index: 0, prompt: 'Sample question: what is 3 + 4?', hint: 'Count on from 3.' }

describe('DemoPracticeDelivery', () => {
  it('shows the hint text, not just the label (en)', () => {
    render(<DemoPracticeDelivery items={[item]} busy={false} onAnswer={() => {}} />)
    expect(screen.getByText('Hint: Count on from 3.')).toBeTruthy()
  })

  it('shows the hint text, not just the label (es)', async () => {
    await i18n.changeLanguage('es')
    render(<DemoPracticeDelivery items={[item]} busy={false} onAnswer={() => {}} />)
    expect(screen.getByText('Pista: Count on from 3.')).toBeTruthy()
  })

  it('shows no hint line when the item has none', () => {
    render(<DemoPracticeDelivery items={[{ ...item, hint: '' }]} busy={false} onAnswer={() => {}} />)
    expect(screen.queryByText(/^Hint/)).toBeNull()
  })
})
