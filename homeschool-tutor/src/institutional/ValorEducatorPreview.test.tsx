import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ValorEducatorPreview from './ValorEducatorPreview'

describe('Valor educator design review', () => {
  it('labels fictional data and does not claim production access', () => {
    render(<ValorEducatorPreview />)
    expect(screen.getByText(/Design review only/)).toBeTruthy()
    expect(screen.getByText(/PROTOTYPE \/ FICTIONAL DATA/)).toBeTruthy()
  })
  it('moves between lesson examples and evidence without student rankings', () => {
    render(<ValorEducatorPreview />)
    fireEvent.click(screen.getByRole('button', { name: /Lesson companion/i }))
    expect(screen.getByText('The art of a good question')).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: /View sample question/i })[0])
    expect(screen.getByText(/What in the assigned reading/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Learning evidence/i }))
    expect(screen.getByText('Explain a passage in your own words')).toBeTruthy()
    expect(screen.queryByText(/leaderboard/i)).toBeNull()
  })
})
