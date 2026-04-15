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

const RANGE_COST_LABELS = {
  '1h': 'last 1h',
  '1d': 'last 24h',
  '3d': 'last 3d',
  '1w': 'last 1w',
  '2w': 'last 2w',
  '1m': 'last 1m',
  '6m': 'last 6m',
}

export default function StatsBar({ stats, timeRange }) {
  const s = stats || {}
  const costLabel = `Cost (${RANGE_COST_LABELS[timeRange] ?? 'period'})`

  const tiles = [
    {
      label: 'Sessions',
      value: s.total_sessions ?? '—',
      sub: `${s.active_sessions ?? 0} active`,
      accent: 'accent',
    },
    {
      label: costLabel,
      value: fmtCost(s.cost_today_usd ?? 0),
      sub: `${fmtCost(s.total_cost_usd ?? 0)} total`,
      accent: 'cost',
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
      accent: 'sub',
    },
  ]

  return (
    <div className="stats-bar">
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
