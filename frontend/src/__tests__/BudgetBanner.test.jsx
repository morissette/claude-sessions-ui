import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import BudgetBanner from '../components/BudgetBanner'

const noExceeded = { daily: { limit: 10, spent: 5, exceeded: false, pct: 50 }, weekly: null }
const dailyExceeded = { daily: { limit: 10, spent: 12, exceeded: true, pct: 120 }, weekly: null }
const bothExceeded = {
  daily: { limit: 10, spent: 12, exceeded: true, pct: 120 },
  weekly: { limit: 50, spent: 55, exceeded: true, pct: 110 },
}

describe('BudgetBanner', () => {
  it('renders nothing when no budget exceeded', () => {
    const { container } = render(<BudgetBanner status={noExceeded} onDismiss={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders banner when daily exceeded', () => {
    render(<BudgetBanner status={dailyExceeded} onDismiss={() => {}} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/daily/i)).toBeInTheDocument()
  })

  it('renders both budgets when both exceeded', () => {
    render(<BudgetBanner status={bothExceeded} onDismiss={() => {}} />)
    expect(screen.getByText(/daily.*weekly|weekly.*daily/i)).toBeInTheDocument()
  })

  it('dismiss button calls onDismiss', () => {
    const onDismiss = vi.fn()
    render(<BudgetBanner status={dailyExceeded} onDismiss={onDismiss} />)
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(onDismiss).toHaveBeenCalledOnce()
  })
})
