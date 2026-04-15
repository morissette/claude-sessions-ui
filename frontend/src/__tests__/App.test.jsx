import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import App from '../App'

// Mock WebSocket globally
class MockWebSocket {
  constructor() {
    this.readyState = WebSocket.CONNECTING
    MockWebSocket.instance = this
  }
  close() { this.readyState = WebSocket.CLOSED }
  send() {}
}
MockWebSocket.CONNECTING = 0
MockWebSocket.OPEN = 1
MockWebSocket.CLOSING = 2
MockWebSocket.CLOSED = 3

beforeEach(() => {
  vi.stubGlobal('WebSocket', MockWebSocket)
  // Silence fetch calls (Ollama check)
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ json: () => Promise.resolve({}) })))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App time range selector', () => {
  it('renders all 7 time range buttons', () => {
    render(<App />)
    for (const label of ['1h', '1d', '3d', '1w', '2w', '1m', '6m']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('defaults to 1d as the active range', () => {
    render(<App />)
    const btn = screen.getByRole('button', { name: '1d' })
    expect(btn.className).toContain('sort-active')
  })

  it('activates clicked range button', async () => {
    const user = userEvent.setup()
    render(<App />)
    const btn1w = screen.getByRole('button', { name: '1w' })
    await user.click(btn1w)
    expect(btn1w.className).toContain('sort-active')
    // 1d should no longer be active
    expect(screen.getByRole('button', { name: '1d' }).className).not.toContain('sort-active')
  })

  it('shows Range label next to time range buttons', () => {
    render(<App />)
    expect(screen.getByText('Range')).toBeInTheDocument()
  })
})
