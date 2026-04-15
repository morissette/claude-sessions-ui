import { useState, useEffect } from 'react'
import './TrendsChart.css'

function BudgetInput({ value, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')

  return editing ? (
    <span className="budget-input">
      $<input type="number" min="0" step="0.01" value={draft}
              onChange={e => setDraft(e.target.value)} style={{width:'80px'}} />
      <button onClick={() => { onSave(draft !== '' ? parseFloat(draft) : null); setEditing(false) }}>Save</button>
      <button onClick={() => setEditing(false)}>Cancel</button>
    </span>
  ) : (
    <button type="button" className="budget-input budget-input--display" onClick={() => { setDraft(value ?? ''); setEditing(true) }}>
      Daily budget: {value != null ? `$${Number(value).toFixed(2)}` : 'not set'} ✎
    </button>
  )
}

export default function TrendsChart({ timeRange }) {
  const [fetchState, setFetchState] = useState({ data: null, loading: true })
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    // Map the app's time range to the nearest available trend range
    const trendRange = {
      '1h': '1d', '1d': '1d', '3d': '1w', '1w': '2w', '2w': '4w',
      '1m': '3m', '6m': '3m', 'all': '3m',
    }[timeRange] ?? '4w'
    fetch(`/api/trends?range=${trendRange}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setFetchState({ data: d, loading: false }) })
      .catch(() => { if (!cancelled) setFetchState(prev => ({ ...prev, loading: false })) })
    return () => { cancelled = true }
  }, [timeRange, refreshKey])

  async function handleBudgetSave(val) {
    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_usd: val }),
    })
    setFetchState(prev => ({ ...prev, loading: true }))
    setRefreshKey(k => k + 1)
  }

  const { data, loading } = fetchState

  if (loading) return <div className="trends-chart trends-chart--loading">Loading…</div>
  if (!data) return null

  const days = data.days || []
  const budget = data.daily_budget_usd

  // Compute chart dimensions
  const W = 700, H = 160, LABEL_H = 24, CHART_H = H - LABEL_H
  const n = days.length
  if (n === 0) return (
    <div className="trends-chart">
      <div className="trends-chart__header">
        <BudgetInput value={budget} onSave={handleBudgetSave} />
      </div>
      <div className="trends-chart__empty">No data for this period.</div>
    </div>
  )

  const maxCost = Math.max(...days.map(d => d.total_cost_usd), budget || 0, 0.001)
  const BAR_W = Math.max(2, W / n - 1)

  // Get unique models across all days
  const allModels = [...new Set(days.flatMap(d => Object.keys(d.by_model || {})))]
  const MODEL_COLORS = ['#06b6d4','#8b5cf6','#f59e0b','#10b981','#ef4444','#3b82f6','#f97316','#84cc16']

  const bars = days.map((day, i) => {
    const x = i * (W / n)
    let yOffset = 0
    const rects = allModels.map((model, mi) => {
      const cost = (day.by_model || {})[model] || 0
      if (cost <= 0) return null
      const barH = (cost / maxCost) * CHART_H
      const y = CHART_H - yOffset - barH
      yOffset += barH
      return <rect key={model} x={x} y={y} width={BAR_W - 0.5} height={barH} fill={MODEL_COLORS[mi % MODEL_COLORS.length]} opacity={0.85} />
    }).filter(Boolean)
    return <g key={day.date}>{rects}</g>
  })

  // Budget line — use != null so budget=0 still renders a line at the bottom
  const budgetY = budget != null ? CHART_H - (budget / maxCost) * CHART_H : null

  // X-axis labels every 7 days
  const labels = days
    .map((d, i) => i % 7 === 0 ? <text key={d.date} x={i * (W / n) + BAR_W / 2} y={H - 4} fontSize="10" fill="var(--text-muted)" textAnchor="middle">{d.date.slice(5)}</text> : null)
    .filter(Boolean)

  return (
    <div className="trends-chart">
      <div className="trends-chart__header">
        <BudgetInput value={budget} onSave={handleBudgetSave} />
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="trends-chart__svg" preserveAspectRatio="xMidYMid meet">
        {bars}
        {budgetY != null && (
          <line x1={0} y1={budgetY} x2={W} y2={budgetY}
                stroke="var(--color-warning, #f59e0b)" strokeDasharray="4 2" strokeWidth={1.5} />
        )}
        {labels}
      </svg>
      <div className="trends-chart__legend">
        {allModels.map((m, i) => (
          <span key={m} className="trends-chart__legend-item">
            <span className="trends-chart__legend-dot" style={{background: MODEL_COLORS[i % MODEL_COLORS.length]}} />
            {m}
          </span>
        ))}
      </div>
    </div>
  )
}
