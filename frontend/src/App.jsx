import { useState, useEffect, useCallback, useRef } from 'react'
import SessionCard from './components/SessionCard'
import StatsBar from './components/StatsBar'
import SavingsBanner from './components/SavingsBanner'
import './App.css'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

export default function App() {
  const [data, setData] = useState({ sessions: [], stats: {}, savings: {}, truncation: {} })
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('activity') // activity | cost | turns
  const [connected, setConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [ollama, setOllama] = useState({ available: false, model_ready: false, model: '' })
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      clearTimeout(reconnectRef.current)
    }
    ws.onclose = () => {
      setConnected(false)
      reconnectRef.current = setTimeout(connect, 3000) // eslint-disable-line react-hooks/immutability
    }
    ws.onerror = () => ws.close()
    ws.onmessage = (e) => {
      try {
        setData(JSON.parse(e.data))
        setLastUpdate(new Date())
      } catch {}
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
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

      <StatsBar stats={stats} />
      <SavingsBanner savings={data.savings} truncation={data.truncation} ollama={ollama} />

      <div className="toolbar">
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
        {sorted.length === 0 ? (
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
              <SessionCard key={session.session_id} session={session} ollama={ollama} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
