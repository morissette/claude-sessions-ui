import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import BatchActionBar from '../components/BatchActionBar'

const noop = () => {}

describe('BatchActionBar', () => {
  it('renders with disabled action buttons when count is 0', () => {
    render(
      <BatchActionBar count={0} onSelectAll={noop} onDeselectAll={noop}
        onSummarize={noop} onExport={noop} onCostReport={noop} ollamaAvailable={true} />
    )
    expect(screen.getByText('0 selected')).toBeInTheDocument()
    expect(screen.getByText('Summarize')).toBeDisabled()
    expect(screen.getByText('Export ZIP')).toBeDisabled()
    expect(screen.getByText('Cost CSV')).toBeDisabled()
  })

  it('renders when count > 0', () => {
    render(
      <BatchActionBar count={3} onSelectAll={noop} onDeselectAll={noop}
        onSummarize={noop} onExport={noop} onCostReport={noop} ollamaAvailable={true} />
    )
    expect(screen.getByText('3 selected')).toBeInTheDocument()
  })

  it('disables Summarize when ollama not available', () => {
    render(
      <BatchActionBar count={2} onSelectAll={noop} onDeselectAll={noop}
        onSummarize={noop} onExport={noop} onCostReport={noop} ollamaAvailable={false} />
    )
    expect(screen.getByText('Summarize')).toBeDisabled()
  })

  it('enables Summarize when ollama available', () => {
    render(
      <BatchActionBar count={2} onSelectAll={noop} onDeselectAll={noop}
        onSummarize={noop} onExport={noop} onCostReport={noop} ollamaAvailable={true} />
    )
    expect(screen.getByText('Summarize')).not.toBeDisabled()
  })

  it('calls onSelectAll when All clicked', () => {
    const onSelectAll = vi.fn()
    render(
      <BatchActionBar count={1} onSelectAll={onSelectAll} onDeselectAll={noop}
        onSummarize={noop} onExport={noop} onCostReport={noop} ollamaAvailable={true} />
    )
    fireEvent.click(screen.getByText('All'))
    expect(onSelectAll).toHaveBeenCalledOnce()
  })
})
