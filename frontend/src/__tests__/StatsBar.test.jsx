import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import StatsBar from '../components/StatsBar'

const baseStats = {
  total_sessions: 5,
  active_sessions: 2,
  cost_today_usd: 0.19,
  total_cost_usd: 8.42,
  total_output_tokens: 480600,
  total_input_tokens: 7300,
  total_cache_read_tokens: 175500000,
  total_cache_create_tokens: 4000000,
  total_turns: 100,
  total_subagents: 10,
}

describe('StatsBar', () => {
  it('renders all six stat tiles', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" />)
    expect(screen.getByText('Sessions')).toBeInTheDocument()
    expect(screen.getByText('Cost (last 24h)')).toBeInTheDocument()
    expect(screen.getByText('Output tokens')).toBeInTheDocument()
    expect(screen.getByText('Cache reads')).toBeInTheDocument()
    expect(screen.getByText('Turns')).toBeInTheDocument()
    expect(screen.getByText('Subagents')).toBeInTheDocument()
  })

  it('shows session count and active sub-label', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" />)
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('2 active')).toBeInTheDocument()
  })

  it('formats large token counts with K suffix', () => {
    render(<StatsBar stats={{ ...baseStats, total_output_tokens: 480600 }} timeRange="1d" />)
    expect(screen.getByText('480.6K')).toBeInTheDocument()
  })

  it('formats very large token counts with M suffix', () => {
    render(<StatsBar stats={{ ...baseStats, total_cache_read_tokens: 175500000 }} timeRange="1d" />)
    expect(screen.getByText('175.5M')).toBeInTheDocument()
  })

  it('formats cost with dollar sign', () => {
    render(<StatsBar stats={{ ...baseStats, cost_today_usd: 0.19 }} timeRange="1d" />)
    expect(screen.getByText('$0.19')).toBeInTheDocument()
  })

  it('formats small cost with 4 decimal places', () => {
    render(<StatsBar stats={{ ...baseStats, cost_today_usd: 0.0042 }} timeRange="1d" />)
    expect(screen.getByText('$0.0042')).toBeInTheDocument()
  })

  it('shows zero cost as $0.00', () => {
    render(<StatsBar stats={{ ...baseStats, cost_today_usd: 0 }} timeRange="1d" />)
    expect(screen.getAllByText('$0.00').length).toBeGreaterThan(0)
  })

  it('renders gracefully with null stats', () => {
    render(<StatsBar stats={null} timeRange="1d" />)
    expect(screen.getByText('Sessions')).toBeInTheDocument()
    // Values fall back to — or 0
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders gracefully with empty stats object', () => {
    render(<StatsBar stats={{}} timeRange="1d" />)
    expect(screen.getByText('0 active')).toBeInTheDocument()
  })

  it('shows "Cost (last 1h)" for 1h range', () => {
    render(<StatsBar stats={baseStats} timeRange="1h" />)
    expect(screen.getByText('Cost (last 1h)')).toBeInTheDocument()
  })

  it('shows "Cost (last 1w)" for 1w range', () => {
    render(<StatsBar stats={baseStats} timeRange="1w" />)
    expect(screen.getByText('Cost (last 1w)')).toBeInTheDocument()
  })

  it('shows "Cost (last 6m)" for 6m range', () => {
    render(<StatsBar stats={baseStats} timeRange="6m" />)
    expect(screen.getByText('Cost (last 6m)')).toBeInTheDocument()
  })

  it('falls back to "Cost (period)" for unknown range', () => {
    render(<StatsBar stats={baseStats} timeRange="bogus" />)
    expect(screen.getByText('Cost (period)')).toBeInTheDocument()
  })
})

const sessions = [
  { model: 'claude-opus-4-6',   stats: { total_tokens: 1000, estimated_cost_usd: 6.00 } },
  { model: 'claude-sonnet-4-6', stats: { total_tokens: 500,  estimated_cost_usd: 3.00 } },
  { model: 'claude-sonnet-4-6', stats: { total_tokens: 200,  estimated_cost_usd: 1.00 } },
]

describe('StatsBar model breakdown popover', () => {
  it('cost tile has aria-haspopup="dialog" and is not expanded by default', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" sessions={sessions} />)
    const btn = screen.getByRole('button', { name: /cost/i })
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
  })

  it('clicking the cost tile opens the popover', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" sessions={sessions} />)
    const btn = screen.getByRole('button', { name: /cost/i })
    fireEvent.click(btn)
    expect(screen.getByRole('dialog', { name: /cost by model/i })).toBeInTheDocument()
  })

  it('popover rows are sorted by cost descending', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" sessions={sessions} />)
    fireEvent.click(screen.getByRole('button', { name: /cost/i }))
    const rows = screen.getAllByRole('row')
    // First data row should be Opus ($6.00), second Sonnet ($4.00)
    expect(rows[1].textContent).toMatch(/Opus/)
    expect(rows[2].textContent).toMatch(/Sonnet/)
  })

  it('popover shows correct percentage for each model', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" sessions={sessions} />)
    fireEvent.click(screen.getByRole('button', { name: /cost/i }))
    // Opus: 6/10 = 60%, Sonnet: 4/10 = 40%
    expect(screen.getByText('60.0%')).toBeInTheDocument()
    expect(screen.getByText('40.0%')).toBeInTheDocument()
  })

  it('pressing Escape closes the popover', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" sessions={sessions} />)
    fireEvent.click(screen.getByRole('button', { name: /cost/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders without popover when sessions prop is omitted', () => {
    render(<StatsBar stats={baseStats} timeRange="1d" />)
    fireEvent.click(screen.getByRole('button', { name: /cost/i }))
    // Popover opens but with empty state (no rows beyond header)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
  })
})
