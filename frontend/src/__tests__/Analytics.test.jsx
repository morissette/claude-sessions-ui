import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import Analytics from '../components/Analytics'

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const emptyAnalytics = {
  session_metrics: {
    total_wall_time_seconds: 0,
    estimated_time_saved_hours: 0.0,
    total_sessions: 0,
    sessions_with_duration: 0,
    avg_cost_per_turn: 0,
    avg_tokens_per_turn: 0,
    cache_efficiency_pct: 0.0,
    cache_savings_usd: 0.0,
    longest_sessions: [],
    most_expensive_sessions: [],
    most_turns_sessions: [],
    most_subagents_sessions: [],
    projects_by_sessions: [],
    projects_by_cost: [],
    model_distribution: [],
    active_hours: Array.from({ length: 24 }, (_, h) => ({ hour: h, count: 0 })),
    top_tools: [],
  },
}

const fullAnalytics = {
  session_metrics: {
    total_wall_time_seconds: 7200,
    estimated_time_saved_hours: 3.5,
    total_sessions: 42,
    sessions_with_duration: 40,
    avg_cost_per_turn: 0.002,
    avg_tokens_per_turn: 1500,
    cache_efficiency_pct: 72.5,
    cache_savings_usd: 1.23,
    longest_sessions: [
      { session_id: 's1', title: 'Long Session', project_name: 'my-project', duration_seconds: 3600, cost_usd: 0.5 },
    ],
    most_expensive_sessions: [
      { session_id: 's2', title: 'Expensive', project_name: 'my-project', cost_usd: 2.0, duration_seconds: 1800 },
    ],
    most_turns_sessions: [
      { session_id: 's3', title: 'Chatty', project_name: 'my-project', turns: 50, cost_usd: 0.1 },
    ],
    most_subagents_sessions: [],
    projects_by_sessions: [
      { project_name: 'my-project', session_count: 15, total_cost_usd: 3.0 },
    ],
    projects_by_cost: [
      { project_name: 'my-project', session_count: 15, total_cost_usd: 3.0 },
    ],
    model_distribution: [
      { model: 'claude-sonnet-4-6', session_count: 42, total_cost_usd: 3.0, pct: 100.0 },
    ],
    active_hours: Array.from({ length: 24 }, (_, h) => ({ hour: h, count: h === 14 ? 10 : 0 })),
    top_tools: [
      { tool: 'Read', count: 100 },
      { tool: 'Edit', count: 50 },
    ],
  },
}

const memoryTree = {
  type: 'directory',
  name: 'memory',
  children: [
    { type: 'file', name: 'user_profile.md', path: '/memory/user_profile.md', size: 512, mtime: 1700000000 },
    { type: 'file', name: 'feedback_style.md', path: '/memory/feedback_style.md', size: 256, mtime: 1699000000 },
  ],
}

const miscStats = {
  customization: {
    skills_count: 3,
    skills: ['commit', 'review', 'deploy'],
    commands_count: 2,
    commands: ['fix', 'test'],
    agents_count: 1,
    hooks_count: 2,
    hook_names: ['redact', 'truncate'],
    hook_events_configured: ['PostToolUse'],
    plugins: [],
    plugin_count: 0,
    enabled_plugins: [],
    permissions_allow_count: 5,
    permissions_deny_count: 3,
    env_vars_count: 1,
    todos_count: 4,
  },
  knowledge: {
    session_summary_count: 10,
    total_sessions_db: 42,
    summary_coverage_pct: 23.8,
    memory_by_type: { user: 2, feedback: 3, project: 1 },
    project_memory_bases: 2,
    plans_count: 1,
    plans_total_bytes: 8192,
  },
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('Analytics', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mockFetch(analyticsPayload, memoryPayload = { type: 'directory', children: [] }, miscPayload = null) {
    fetch.mockImplementation((url) => {
      if (url.includes('/api/analytics')) {
        return Promise.resolve({ json: () => Promise.resolve(analyticsPayload) })
      }
      if (url.includes('/api/memory')) {
        return Promise.resolve({ json: () => Promise.resolve(memoryPayload) })
      }
      if (url.includes('/api/misc-stats')) {
        return Promise.resolve({ json: () => Promise.resolve(miscPayload || { customization: {}, knowledge: {} }) })
      }
      return Promise.resolve({ json: () => Promise.resolve({}) })
    })
  }

  it('shows loading state initially', () => {
    fetch.mockImplementation(() => new Promise(() => {}))
    render(<Analytics timeRange="1d" />)
    expect(screen.getByText('Loading analytics…')).toBeInTheDocument()
  })

  it('shows "no data" when fetch returns no analytics', async () => {
    fetch.mockImplementation(() => Promise.reject(new Error('network error')))
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('No analytics data available.')).toBeInTheDocument()
    })
  })

  it('renders Session Analytics pane title', async () => {
    mockFetch(emptyAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Session Analytics')).toBeInTheDocument()
    })
  })

  it('renders Memory Analytics pane title', async () => {
    mockFetch(emptyAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Memory Analytics')).toBeInTheDocument()
    })
  })

  it('renders KPI tiles for empty analytics data', async () => {
    mockFetch(emptyAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Time Spent')).toBeInTheDocument()
      expect(screen.getByText('Est. Time Saved')).toBeInTheDocument()
      expect(screen.getByText('Cache Efficiency')).toBeInTheDocument()
      expect(screen.getByText('Cache Savings')).toBeInTheDocument()
    })
  })

  it('renders correct values for full analytics data', async () => {
    mockFetch(fullAnalytics, memoryTree, miscStats)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      // Wall time: 7200s = 2h 0m
      expect(screen.getByText('2h 0m')).toBeInTheDocument()
      // Estimated time saved
      expect(screen.getByText('3.5h')).toBeInTheDocument()
      // Cache efficiency
      expect(screen.getByText('72.5%')).toBeInTheDocument()
    })
  })

  it('renders ranked session cards when data present', async () => {
    mockFetch(fullAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Longest Sessions')).toBeInTheDocument()
      expect(screen.getByText('Long Session')).toBeInTheDocument()
    })
  })

  it('renders Top Tools chart card always (empty state visible)', async () => {
    mockFetch(emptyAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Top Tools Used (across all sessions in range)')).toBeInTheDocument()
    })
  })

  it('renders tool names in tools chart when tools present', async () => {
    mockFetch(fullAnalytics)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Read')).toBeInTheDocument()
      expect(screen.getByText('Edit')).toBeInTheDocument()
    })
  })

  it('renders memory file count when memory tree provided', async () => {
    mockFetch(fullAnalytics, memoryTree, miscStats)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Total Files')).toBeInTheDocument()
    })
  })

  it('renders Customization section when miscStats present', async () => {
    mockFetch(emptyAnalytics, memoryTree, miscStats)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Customization')).toBeInTheDocument()
    })
  })

  it('renders Knowledge Base section when miscStats present', async () => {
    mockFetch(emptyAnalytics, memoryTree, miscStats)
    render(<Analytics timeRange="1d" />)
    await waitFor(() => {
      expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
    })
  })

  it('re-fetches analytics when timeRange prop changes', async () => {
    mockFetch(emptyAnalytics)
    const { rerender } = render(<Analytics timeRange="1d" />)
    await waitFor(() => screen.getByText('Session Analytics'))

    rerender(<Analytics timeRange="1w" />)
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining('time_range=1w'))
    })
  })
})
