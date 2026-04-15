import './SessionAnalytics.css'

function TurnTokenChart({ turns }) {
  if (!turns || turns.length === 0) return null
  const W = 600, H = 160, LABEL_H = 20, CHART_H = H - LABEL_H
  const max = Math.max(...turns.map(t => t.input_tokens + t.output_tokens + t.cache_create_tokens + t.cache_read_tokens), 1)
  const bw = Math.max(2, W / turns.length - 1)
  const bars = turns.map((t, i) => {
    const x = i * (W / turns.length)
    const scale = CHART_H / max
    let y = CHART_H
    const rects = []
    const layers = [
      { val: t.cache_read_tokens, color: '#10b981' },
      { val: t.cache_create_tokens, color: '#8b5cf6' },
      { val: t.output_tokens, color: '#06b6d4' },
      { val: t.input_tokens, color: '#3b82f6' },
    ]
    for (const { val, color } of layers) {
      if (val <= 0) continue
      const h = val * scale
      y -= h
      rects.push(<rect key={color} x={x} y={y} width={bw - 0.5} height={h} fill={color} opacity={0.85} />)
    }
    return <g key={i}>{rects}</g>
  })
  return (
    <div>
      <div className="analytics__chart-title">Turn-by-Turn Tokens</div>
      {turns.length > 200 && <div className="analytics__notice">Showing first 200 turns</div>}
      <svg viewBox={`0 0 ${W} ${H}`} className="analytics__svg" preserveAspectRatio="xMidYMid meet">
        {bars}
        <text x={0} y={H - 4} fontSize="10" fill="var(--text-muted)">Turn 1</text>
        <text x={W} y={H - 4} fontSize="10" fill="var(--text-muted)" textAnchor="end">Turn {turns.length}</text>
      </svg>
      <div className="analytics__legend">
        {[['#3b82f6','Input'],['#06b6d4','Output'],['#8b5cf6','Cache write'],['#10b981','Cache read']].map(([c,l]) => (
          <span key={l} className="analytics__legend-item">
            <span style={{background:c,width:10,height:10,display:'inline-block',borderRadius:2,marginRight:3}} />
            {l}
          </span>
        ))}
      </div>
    </div>
  )
}

function CumulativeCostChart({ cumulative }) {
  if (!cumulative || cumulative.length === 0) return null
  const W = 600, H = 100
  const maxCost = Math.max(...cumulative.map(p => p.cost_usd), 0.0001)
  const points = cumulative.map((p, i) => {
    const x = (i / (cumulative.length - 1 || 1)) * W
    const y = H - (p.cost_usd / maxCost) * (H - 10)
    return `${x},${y}`
  }).join(' ')
  const areaPoints = `0,${H} ` + points + ` ${W},${H}`
  return (
    <div>
      <div className="analytics__chart-title">Cumulative Cost</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="analytics__svg" preserveAspectRatio="xMidYMid meet">
        <polygon points={areaPoints} fill="var(--color-accent, #06b6d4)" opacity={0.15} />
        <polyline points={points} fill="none" stroke="var(--color-accent, #06b6d4)" strokeWidth={2} />
        <text x={W} y={H - 2} fontSize="10" fill="var(--text-muted)" textAnchor="end">
          ${maxCost.toFixed(4)}
        </text>
      </svg>
    </div>
  )
}

function ToolUsageChart({ toolUsage }) {
  if (!toolUsage || toolUsage.length === 0) return <div className="analytics__empty">No tool calls recorded.</div>
  const MAX_BAR = 300
  const maxCount = Math.max(...toolUsage.map(t => t.count), 1)
  return (
    <div>
      <div className="analytics__chart-title">Tool Usage (Top {toolUsage.length})</div>
      <svg viewBox={`0 0 400 ${toolUsage.length * 24}`} className="analytics__svg-tools" preserveAspectRatio="xMidYMid meet">
        {toolUsage.map((t, i) => (
          <g key={t.tool} transform={`translate(0,${i * 24})`}>
            <text x={0} y={16} fontSize="11" fill="var(--text)">{t.tool}</text>
            <rect x={90} y={4} width={(t.count / maxCount) * MAX_BAR} height={14} fill="var(--color-accent, #06b6d4)" opacity={0.8} rx={2} />
            <text x={95 + (t.count / maxCount) * MAX_BAR} y={16} fontSize="10" fill="var(--text-muted)">{t.count}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}

export default function SessionAnalytics({ data, loading }) {
  if (loading) return <div className="analytics__loading">Loading analytics&#8230;</div>
  if (!data) return null

  const { turns, cumulative_cost, tool_usage, summary } = data

  return (
    <div className="session-analytics">
      <div className="analytics__stats">
        <div className="analytics__stat">
          <span className="analytics__stat-value">{summary.total_turns}</span>
          <span className="analytics__stat-label">Turns</span>
        </div>
        {summary.avg_turn_duration_s != null && (
          <div className="analytics__stat">
            <span className="analytics__stat-value">{summary.avg_turn_duration_s.toFixed(1)}s</span>
            <span className="analytics__stat-label">Avg turn</span>
          </div>
        )}
        <div className="analytics__stat">
          <span className="analytics__stat-value">{(summary.thinking_ratio * 100).toFixed(0)}%</span>
          <span className="analytics__stat-label">Thinking</span>
        </div>
        <div className="analytics__stat">
          <span className="analytics__stat-value">${summary.peak_turn_cost_usd.toFixed(4)}</span>
          <span className="analytics__stat-label">Peak turn cost</span>
        </div>
      </div>
      <TurnTokenChart turns={turns} />
      <CumulativeCostChart cumulative={cumulative_cost} />
      <ToolUsageChart toolUsage={tool_usage} />
    </div>
  )
}
