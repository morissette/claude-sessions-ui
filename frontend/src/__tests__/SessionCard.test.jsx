import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import SessionCard from '../components/SessionCard'

const baseSession = {
  session_id: 'abc123def456',
  project_name: 'my-project',
  project_path: '/home/user/work/my-project',
  git_branch: 'main',
  title: 'Fix the authentication bug in login flow',
  model: 'claude-sonnet-4-6',
  turns: 5,
  subagent_count: 0,
  subagents: [],
  is_active: false,
  pid: null,
  last_active: new Date(Date.now() - 60_000).toISOString(), // 1 min ago
  last_activity: null,
  ai_summary: null,
  compact_potential_usd: 0,
  stats: {
    input_tokens: 1000,
    output_tokens: 500,
    cache_create_tokens: 2000,
    cache_read_tokens: 8000,
    total_tokens: 11500,
    estimated_cost_usd: 0.042,
  },
}

const ollamaOff = { model_ready: false, model: 'llama3.2:3b' }
const ollamaReady = { model_ready: true, model: 'llama3.2:3b' }

describe('SessionCard', () => {
  it('renders project name', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('my-project')).toBeInTheDocument()
  })

  it('renders git branch', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('main')).toBeInTheDocument()
  })

  it('renders session title', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('Fix the authentication bug in login flow')).toBeInTheDocument()
  })

  it('renders ai_summary instead of title when present', () => {
    const session = { ...baseSession, ai_summary: 'Fix auth bug in login' }
    render(<SessionCard session={session} ollama={ollamaOff} />)
    expect(screen.getByText('Fix auth bug in login')).toBeInTheDocument()
    expect(screen.queryByText('Fix the authentication bug in login flow')).not.toBeInTheDocument()
  })

  it('shows Sonnet model badge', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('Sonnet')).toBeInTheDocument()
  })

  it('shows Opus model badge', () => {
    render(<SessionCard session={{ ...baseSession, model: 'claude-opus-4-6' }} ollama={ollamaOff} />)
    expect(screen.getByText('Opus')).toBeInTheDocument()
  })

  it('shows Haiku model badge', () => {
    render(<SessionCard session={{ ...baseSession, model: 'claude-haiku-4-5' }} ollama={ollamaOff} />)
    expect(screen.getByText('Haiku')).toBeInTheDocument()
  })

  it('shows turns badge', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('5 turns')).toBeInTheDocument()
  })

  it('pluralizes turn correctly', () => {
    render(<SessionCard session={{ ...baseSession, turns: 1 }} ollama={ollamaOff} />)
    expect(screen.getByText('1 turn')).toBeInTheDocument()
  })

  it('shows Idle badge for inactive session', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('Idle')).toBeInTheDocument()
  })

  it('shows Active badge for active session', () => {
    render(<SessionCard session={{ ...baseSession, is_active: true, pid: 12345 }} ollama={ollamaOff} />)
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows PID when session is active', () => {
    render(<SessionCard session={{ ...baseSession, is_active: true, pid: 57396 }} ollama={ollamaOff} />)
    expect(screen.getByText('PID 57396')).toBeInTheDocument()
  })

  it('does not show PID when session is idle', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.queryByText(/PID/)).not.toBeInTheDocument()
  })

  it('shows subagent badge when subagents present', () => {
    const session = {
      ...baseSession,
      subagent_count: 3,
      subagents: [
        { id: '1', agent_type: 'Explore' },
        { id: '2', agent_type: 'Plan' },
        { id: '3', agent_type: 'general-purpose' },
      ],
    }
    render(<SessionCard session={session} ollama={ollamaOff} />)
    expect(screen.getByText('⚡ 3 subagents')).toBeInTheDocument()
  })

  it('shows subagent type chips', () => {
    const session = {
      ...baseSession,
      subagent_count: 1,
      subagents: [{ id: '1', agent_type: 'Explore' }],
    }
    render(<SessionCard session={session} ollama={ollamaOff} />)
    expect(screen.getByText('Explore')).toBeInTheDocument()
  })

  it('shows summarize button when ollama is ready and no summary', () => {
    render(<SessionCard session={baseSession} ollama={ollamaReady} />)
    expect(screen.getByTitle(`Summarize with ${ollamaReady.model}`)).toBeInTheDocument()
  })

  it('does not show summarize button when ollama not ready', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.queryByTitle(/Summarize with/)).not.toBeInTheDocument()
  })

  it('does not show summarize button when summary already exists', () => {
    const session = { ...baseSession, ai_summary: 'Existing summary' }
    render(<SessionCard session={session} ollama={ollamaReady} />)
    expect(screen.queryByTitle(/Summarize with/)).not.toBeInTheDocument()
  })

  it('shows shortened session id', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('abc123de…')).toBeInTheDocument()
  })

  it('shows cost in card footer', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('$0.042')).toBeInTheDocument()
  })

  it('shows total tokens', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('11.5K')).toBeInTheDocument()
  })

  it('shows last_activity when session is active', () => {
    const session = { ...baseSession, is_active: true, last_activity: 'Bash' }
    render(<SessionCard session={session} ollama={ollamaOff} />)
    expect(screen.getByText('Bash')).toBeInTheDocument()
  })

  it('shows /compact badge when compact_potential_usd is significant', () => {
    render(<SessionCard session={{ ...baseSession, compact_potential_usd: 0.01 }} ollama={ollamaOff} />)
    expect(screen.getByText('⚡ /compact')).toBeInTheDocument()
  })

  it('shows export button', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByText('Export as skill')).toBeInTheDocument()
  })

  it('shows export scope select', () => {
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('shows skill name on successful export', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ skill_name: 'fix-auth-bug', skill_path: '/tmp/fix-auth-bug.md', scope: 'global', ollama_used: false }),
      })
    )
    const user = userEvent.setup()
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    await user.click(screen.getByText('Export as skill'))
    await waitFor(() => expect(screen.getByText('✓ /fix-auth-bug')).toBeInTheDocument())
    vi.restoreAllMocks()
  })

  it('shows retry on export error', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve({ ok: false, text: () => Promise.resolve('error') }))
    const user = userEvent.setup()
    render(<SessionCard session={baseSession} ollama={ollamaOff} />)
    await user.click(screen.getByText('Export as skill'))
    await waitFor(() => expect(screen.getByText('Retry export')).toBeInTheDocument())
    vi.restoreAllMocks()
  })
})
