import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
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
    expect(screen.getByText('Loading…')).toBeInTheDocument()
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
})
