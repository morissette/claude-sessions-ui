import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import SavingsBanner from '../components/SavingsBanner'

const baseSavings = {
  pr_skips: 3,
  pr_saved_usd: 0.15,
  summaries_generated: 30,
  summary_saved_usd: 0.0138,
  total_saved_usd: 1.54,
  recent_skips: [
    { ts: 't1', title: 'chore: bump actions/checkout', url: 'http://a' },
    { ts: 't2', title: 'chore: update go.sum', url: 'http://b' },
  ],
}

const baseTruncation = {
  tools: {
    Bash: { count: 5, tokens_saved: 1000, cost_saved_usd: 0.003 },
  },
  total_tokens_saved: 1000,
  total_cost_saved_usd: 0.003,
}

const ollamaReady = { model_ready: true, model: 'llama3.2:3b' }
const ollamaOff = { model_ready: false, model: 'llama3.2:3b' }

describe('SavingsBanner', () => {
  it('renders null when no activity and ollama not ready', () => {
    const { container } = render(
      <SavingsBanner
        savings={{ pr_skips: 0, summaries_generated: 0, total_saved_usd: 0 }}
        truncation={{ tools: {}, total_tokens_saved: 0 }}
        ollama={ollamaOff}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders when ollama model is ready even with no savings', () => {
    render(
      <SavingsBanner
        savings={{ pr_skips: 0, summaries_generated: 0, total_saved_usd: 0 }}
        truncation={{ tools: {}, total_tokens_saved: 0 }}
        ollama={ollamaReady}
      />
    )
    expect(screen.getByText('llama3.2:3b')).toBeInTheDocument()
  })

  it('shows total saved amount', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('Total saved')).toBeInTheDocument()
  })

  it('shows PR skips count', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('PRs skipped')).toBeInTheDocument()
  })

  it('pluralizes PR correctly for single skip', () => {
    render(
      <SavingsBanner
        savings={{ ...baseSavings, pr_skips: 1 }}
        truncation={baseTruncation}
        ollama={ollamaReady}
      />
    )
    expect(screen.getByText('PR skipped')).toBeInTheDocument()
  })

  it('shows summaries count', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('30')).toBeInTheDocument()
    expect(screen.getByText('summaries')).toBeInTheDocument()
  })

  it('shows recent skip chips', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('chore: bump actions/checkout')).toBeInTheDocument()
  })

  it('shows truncation section when tokens saved > 0', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('Hooks')).toBeInTheDocument()
    expect(screen.getByText('Bash')).toBeInTheDocument()
  })

  it('shows model status dot', () => {
    render(<SavingsBanner savings={baseSavings} truncation={baseTruncation} ollama={ollamaReady} />)
    expect(screen.getByText('llama3.2:3b')).toBeInTheDocument()
  })

  it('renders with undefined savings/truncation', () => {
    render(<SavingsBanner savings={undefined} truncation={undefined} ollama={ollamaReady} />)
    // Should not crash — ollama ready shows the banner
    expect(screen.getByText('llama3.2:3b')).toBeInTheDocument()
  })
})
