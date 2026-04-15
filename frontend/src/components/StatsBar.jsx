import { useState, useEffect } from 'react'
import './StatsBar.css'

function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function fmtCost(n) {
  if (n === 0) return '$0.00'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

function modelShort(model) {
  if (!model || model === 'unknown') return null
  if (model.includes('opus')) return { label: 'Opus', cls: 'model-opus' }
  if (model.includes('sonnet')) return { label: 'Sonnet', cls: 'model-sonnet' }
  if (model.includes('haiku')) return { label: 'Haiku', cls: 'model-haiku' }
  return { label: model.replace('claude-', '').slice(0, 12), cls: 'model-default' }
}

const RANGE_COST_LABELS = {
  '1h': 'last 1h',
  '1d': 'last 24h',
  '3d': 'last 3d',
  '1w': 'last 1w',
  '2w': 'last 2w',
  '1m': 'last 1m',
  '6m': 'last 6m',
}

function ModelBreakdownPopover({ sessions, onClose }) {
  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (!e.target.closest('.stats-bar__tile--cost')) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Compute breakdown
  const byModel = {}
  for (const s of sessions) {
    const m = s.model || 'unknown'
    if (!byModel[m]) byModel[m] = { sessions: 0, tokens: 0, cost: 0 }
    byModel[m].sessions += 1
    byModel[m].tokens   += s.stats?.total_tokens ?? 0
    byModel[m].cost     += s.stats?.estimated_cost_usd ?? 0
  }
  const totalCost = Object.values(byModel).reduce((sum, r) => sum + r.cost, 0)
  const rows = Object.entries(byModel)
    .map(([model, d]) => ({ model, ...d, pct: totalCost > 0 ? d.cost / totalCost * 100 : 0 }))
    .sort((a, b) => b.cost - a.cost)

  return (
    <div className="model-breakdown-popover" role="dialog" aria-label="Cost by model">
      <table className="model-breakdown-popover__table">
        <thead>
          <tr><th>Model</th><th>Sessions</th><th>Tokens</th><th>Cost</th><th>%</th></tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const ms = modelShort(r.model)
            const label = ms ? ms.label : r.model
            const cls = ms ? ms.cls : 'model-default'
            return (
              <tr key={r.model}>
                <td><span className={`badge ${cls}`}>{label}</span></td>
                <td>{r.sessions}</td>
                <td>{fmt(r.tokens)}</td>
                <td>{fmtCost(r.cost)}</td>
                <td>{r.pct.toFixed(1)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function StatsBar({ stats, timeRange, sessions }) {
  const s = stats || {}
  const costLabel = `Cost (${RANGE_COST_LABELS[timeRange] ?? 'period'})`
  const [showModelBreakdown, setShowModelBreakdown] = useState(false)

  const tiles = [
    {
      label: 'Sessions',
      value: s.total_sessions ?? '—',
      sub: `${s.active_sessions ?? 0} active`,
      accent: 'accent',
    },
    {
      label: 'Output tokens',
      value: fmt(s.total_output_tokens ?? 0),
      sub: `${fmt(s.total_input_tokens ?? 0)} input`,
      accent: 'tokens',
    },
    {
      label: 'Cache reads',
      value: fmt(s.total_cache_read_tokens ?? 0),
      sub: `${fmt(s.total_cache_create_tokens ?? 0)} created`,
      accent: 'cache',
    },
    {
      label: 'Turns',
      value: fmt(s.total_turns ?? 0),
      sub: null,
      accent: 'turns',
    },
    {
      label: 'Subagents',
      value: fmt(s.total_subagents ?? 0),
      sub: 'spawned total',
      accent: 'agents',
    },
  ]

  return (
    <div className="stats-bar">
      <div className="stat-tile stat-cost stats-bar__tile--cost" style={{ position: 'relative' }}>
        <button
          className="stats-bar__cost-btn"
          onClick={() => setShowModelBreakdown(v => !v)}
          aria-expanded={showModelBreakdown}
          aria-haspopup="true"
        >
          <span className="stat-value mono">{fmtCost(s.cost_today_usd ?? 0)}</span>
          <span className="stat-label">{costLabel} <span className="stats-bar__cost-caret">▾</span></span>
          <span className="stat-sub">{fmtCost(s.total_cost_usd ?? 0)} total</span>
        </button>
        {showModelBreakdown && (
          <ModelBreakdownPopover
            sessions={sessions || []}
            onClose={() => setShowModelBreakdown(false)}
          />
        )}
      </div>
      {tiles.map(t => (
        <div key={t.label} className={`stat-tile stat-${t.accent}`}>
          <span className="stat-label">{t.label}</span>
          <span className="stat-value mono">{t.value}</span>
          {t.sub && <span className="stat-sub">{t.sub}</span>}
        </div>
      ))}
    </div>
  )
}
