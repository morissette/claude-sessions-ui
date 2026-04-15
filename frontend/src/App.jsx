import { useState, useEffect, useCallback, useRef } from 'react'
import SessionCard from './components/SessionCard'
import StatsBar from './components/StatsBar'
import SavingsBanner from './components/SavingsBanner'
import SessionDetail from './components/SessionDetail'
import { usePersistedState } from './hooks/usePersistedState.js'
import TrendsChart from './components/TrendsChart'
import { ProjectList } from './components/ProjectCard'
import './App.css'

const PREFS_DEFAULTS = {
  version:         1,
  filter:          'all',
  sort:            'activity',
  timeRange:       '1d',
  selectedProject: null,
  viewMode:        'sessions',
}

const TIME_RANGES = [
  { id: '1h',    label: '1h' },
  { id: '1d',    label: '1d' },
  { id: '3d',    label: '3d' },
  { id: '1w',    label: '1w' },
  { id: '2w',    label: '2w' },
  { id: '1m',    label: '1m' },
  { id: '6m',    label: '6m' },
  { id: 'all',   label: 'All' },
  { id: 'custom', label: 'Custom' },
]

export default function App() {
  const [data, setData] = useState({ sessions: [], stats: {}, savings: {}, truncation: {} })
  const [prefs, setPrefs] = usePersistedState('claude-sessions-ui-prefs', PREFS_DEFAULTS)

  // Version check — reset if schema changed
  useEffect(() => {
    if (prefs.version !== PREFS_DEFAULTS.version) {
      setPrefs(PREFS_DEFAULTS)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const { filter, sort, timeRange } = prefs

  const setFilter    = (v) => setPrefs(p => ({...p, filter:    v}))
  const setSort      = (v) => setPrefs(p => ({...p, sort:      v}))
  const setTimeRange = (v) => setPrefs(p => ({...p, timeRange: v}))

  const [connected, setConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [ollama, setOllama] = useState({ available: false, model_ready: false, model: '' })
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd]     = useState('')
  const [customError, setCustomError] = useState('')
  const [trendsExpanded, setTrendsExpanded] = useState(false)
  const [viewMode, setViewMode] = useState('sessions')
  const [selectedProject, setSelectedProject] = useState(null)
  const [projectData, setProjectData] = useState([])
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const intentionalCloseRef = useRef(false)

  function buildWsUrl(tr, cs, ce) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const base = `${proto}://${window.location.host}/ws?time_range=${tr}`
    if (tr === 'custom' && cs && ce) {
      return `${base}&start=${cs}T00:00:00Z&end=${ce}T23:59:59Z`
    }
    return base
  }

  function validateCustomRange(start, end) {
    const today = new Date().toISOString().slice(0, 10)
    if (!start || !end) return 'Both dates are required'
    if (end < start)    return 'End date must be after start date'
    if (end > today)    return 'End date cannot be in the future'
    return ''
  }

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    let wsUrl = buildWsUrl(timeRange, customStart, customEnd)
    if (selectedProject) wsUrl += `&project=${encodeURIComponent(selectedProject)}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      clearTimeout(reconnectRef.current)
    }
    ws.onclose = () => {
      setConnected(false)
      // Only schedule a reconnect for unexpected disconnects, not intentional closes
      // (e.g. timeRange change or unmount). Without this guard the old closure would
      // reconnect with the previous timeRange and create a duplicate connection.
      if (!intentionalCloseRef.current) {
        reconnectRef.current = setTimeout(connect, 3000) // eslint-disable-line react-hooks/immutability
      }
      intentionalCloseRef.current = false
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (e) => {
      try {
        setData(JSON.parse(e.data))
        setLastUpdate(new Date())
      } catch {}
    }
  }, [timeRange, customStart, customEnd, selectedProject])

  useEffect(() => {
    intentionalCloseRef.current = true
    wsRef.current?.close()
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      intentionalCloseRef.current = true
      wsRef.current?.close()
    }
  }, [connect])

  useEffect(() => {
    const checkOllama = () =>
      fetch('/api/ollama').then(r => r.json()).then(setOllama).catch(() => {})
    checkOllama()
    const id = setInterval(checkOllama, 15000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (viewMode !== 'projects') return
    fetch(`/api/projects?time_range=${timeRange}`)
      .then(r => r.json())
      .then(setProjectData)
      .catch(() => {})
  }, [viewMode, timeRange])

  function handleProjectSelect(project) {
    setSelectedProject(project.project_name)
    setViewMode('sessions')
  }

  const sessions = data.sessions || []
  const stats = data.stats || {}

  const midnight = new Date(); midnight.setHours(0, 0, 0, 0)
  const filtered = sessions.filter(s => {
    if (filter === 'active') return s.is_active
    if (filter === 'today') return s.last_active && new Date(s.last_active) >= midnight
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    if (sort === 'cost') return b.stats.estimated_cost_usd - a.stats.estimated_cost_usd
    if (sort === 'turns') return b.turns - a.turns
    // default: active first, then by last_active
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
    return (b.last_active || '') > (a.last_active || '') ? 1 : -1
  })

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              <path d="M2 17l10 5 10-5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              <path d="M2 12l10 5 10-5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="brand-name">Claude Sessions</span>
        </div>

        <div className="header-right">
          {lastUpdate && (
            <span className="last-update mono">
              updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
          <div className={`conn-badge ${ollama.model_ready ? 'conn-live' : 'conn-off'}`} title={ollama.model_ready ? `Local model ready: ${ollama.model}` : 'Ollama not available'}>
            <span className="conn-dot" />
            {ollama.model_ready ? ollama.model : 'No local model'}
          </div>
          <div className={`conn-badge ${connected ? 'conn-live' : 'conn-off'}`}>
            <span className="conn-dot" />
            {connected ? 'Live' : 'Reconnecting'}
          </div>
        </div>
      </header>

      <StatsBar stats={stats} timeRange={timeRange} sessions={sorted} />
      <section className="trends">
        <button className="trends__toggle" onClick={() => setTrendsExpanded(e => !e)}>
          Cost Trends
          <span className={`trends__chevron ${trendsExpanded ? 'open' : ''}`}>▾</span>
        </button>
        {trendsExpanded && <TrendsChart timeRange={timeRange} />}
      </section>
      <SavingsBanner savings={data.savings} truncation={data.truncation} ollama={ollama} />

      <div className="toolbar">
        <div className="toolbar__view-toggle">
          <button
            className={`toolbar__view-btn ${viewMode === 'sessions' ? 'active' : ''}`}
            onClick={() => setViewMode('sessions')}
          >Sessions</button>
          <button
            className={`toolbar__view-btn ${viewMode === 'projects' ? 'active' : ''}`}
            onClick={() => setViewMode('projects')}
          >Projects</button>
        </div>

        {selectedProject && (
          <span className="project-filter__tag">
            {selectedProject}
            <button
              type="button"
              className="project-filter__clear"
              aria-label="Clear project filter"
              onClick={() => setSelectedProject(null)}
            >×</button>
          </span>
        )}

        <div className="filter-tabs">
          <button
            className={`ftab ${filter === 'all' ? 'ftab-active' : ''}`}
            onClick={() => setFilter('all')}
          >
            All
            <span className="ftab-count">{sessions.length}</span>
          </button>
          <button
            className={`ftab ${filter === 'active' ? 'ftab-active' : ''}`}
            onClick={() => setFilter('active')}
          >
            <span className="active-dot" />
            Active
            <span className="ftab-count">{sessions.filter(s => s.is_active).length}</span>
          </button>
          <button
            className={`ftab ${filter === 'today' ? 'ftab-active' : ''}`}
            onClick={() => setFilter('today')}
          >
            Today
            <span className="ftab-count">
              {sessions.filter(s => s.last_active && new Date(s.last_active) >= midnight).length}
            </span>
          </button>
        </div>

        <div className="time-range-tabs">
          <span className="sort-label">Range</span>
          {TIME_RANGES.map(r => (
            <button
              key={r.id}
              className={`sort-btn ${timeRange === r.id ? 'sort-active' : ''}`}
              onClick={() => setTimeRange(r.id)}
            >
              {r.label}
            </button>
          ))}
          {timeRange === 'custom' && (
            <span className="toolbar__date-range">
              <input type="date" value={customStart}
                     onChange={e => { setCustomStart(e.target.value); setCustomError(validateCustomRange(e.target.value, customEnd)) }}
                     max={customEnd || new Date().toISOString().slice(0,10)} />
              <span>–</span>
              <input type="date" value={customEnd}
                     onChange={e => { setCustomEnd(e.target.value); setCustomError(validateCustomRange(customStart, e.target.value)) }}
                     min={customStart} max={new Date().toISOString().slice(0,10)} />
              {customError && <span className="toolbar__date-error">{customError}</span>}
            </span>
          )}
        </div>

        <div className="sort-controls">
          <span className="sort-label">Sort</span>
          {[
            { id: 'activity', label: 'Recent' },
            { id: 'cost', label: 'Cost' },
            { id: 'turns', label: 'Turns' },
          ].map(opt => (
            <button
              key={opt.id}
              className={`sort-btn ${sort === opt.id ? 'sort-active' : ''}`}
              onClick={() => setSort(opt.id)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <main className="sessions-container">
        {viewMode === 'projects'
          ? <ProjectList projects={projectData} onSelect={handleProjectSelect} />
          : sorted.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">◇</div>
              <p className="empty-title">No sessions found</p>
              <p className="empty-sub">
                {filter !== 'all'
                  ? `No ${filter} sessions — try "All"`
                  : 'Start a Claude Code session to see it here'}
              </p>
            </div>
          ) : (
            <div className="sessions-grid">
              {sorted.map(session => (
                <SessionCard
                  key={session.session_id}
                  session={session}
                  ollama={ollama}
                  onSelect={setSelectedSessionId}
                />
              ))}
            </div>
          )
        }
      </main>

      {selectedSessionId && (
        <SessionDetail
          key={selectedSessionId}
          sessionId={selectedSessionId}
          onClose={() => setSelectedSessionId(null)}
          ollama={ollama}
        />
      )}
    </div>
  )
}
