import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import SessionDetail from '../components/SessionDetail'

const mockDetail = {
  session_id: 'abc123',
  total_messages: 2,
  offset: 0,
  limit: 200,
  messages: [
    { id: 0, type: 'user', role: 'user', content: 'Fix the bug', tool_name: null, tool_use_id: null, timestamp: null, thinking: null },
    { id: 1, type: 'assistant', role: 'assistant', content: 'Done!', tool_name: null, tool_use_id: null, timestamp: null, thinking: null },
  ],
}

describe('SessionDetail', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders loading state while fetch is pending', () => {
    vi.stubGlobal('fetch', () => new Promise(() => {}))
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    expect(screen.getByText('Loading messages')).toBeInTheDocument()
  })

  it('renders messages on successful fetch', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Fix the bug')).toBeInTheDocument())
    expect(screen.getByText('Done!')).toBeInTheDocument()
  })

  it('calls onClose when Escape key is pressed', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    const onClose = vi.fn()
    render(<SessionDetail sessionId="abc123" onClose={onClose} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when backdrop is clicked', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    const onClose = vi.fn()
    render(<SessionDetail sessionId="abc123" onClose={onClose} />)
    const overlay = document.querySelector('.detail-overlay')
    fireEvent.click(overlay)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows export as skill button in overlay', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    expect(screen.getByText('Export as skill')).toBeInTheDocument()
  })

  it('shows export scope select in overlay', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('shows skill name on successful export', async () => {
    let callCount = 0
    vi.stubGlobal('fetch', () => {
      callCount++
      if (callCount === 1) {
        return Promise.resolve({ json: () => Promise.resolve(mockDetail) })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ skill_name: 'fix-auth-bug', skill_path: '/tmp/fix-auth-bug.md', scope: 'global', ollama_used: false }),
      })
    })
    const user = userEvent.setup()
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Export')).toBeInTheDocument())
    await user.click(screen.getByText('Export'))
    await waitFor(() => expect(screen.getByText('✓ /fix-auth-bug')).toBeInTheDocument())
  })

  it('shows retry on export error', async () => {
    let callCount = 0
    vi.stubGlobal('fetch', () => {
      callCount++
      if (callCount === 1) {
        return Promise.resolve({ json: () => Promise.resolve(mockDetail) })
      }
      return Promise.resolve({ ok: false, text: () => Promise.resolve('error') })
    })
    const user = userEvent.setup()
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText('Export')).toBeInTheDocument())
    await user.click(screen.getByText('Export'))
    await waitFor(() => expect(screen.getByText('Retry')).toBeInTheDocument())
  })

  it('shows transcript download button', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ json: () => Promise.resolve(mockDetail) })
    )
    render(<SessionDetail sessionId="abc123" onClose={() => {}} />)
    expect(screen.getByTitle('Download transcript as Markdown')).toBeInTheDocument()
  })
})
