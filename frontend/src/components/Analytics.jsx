import { useState, useEffect, useMemo } from 'react'
import { fmt, fmtCost, modelShort } from '../utils.js'
import './Analytics.css'

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function fmtSize(bytes) {
  if (!bytes || bytes <= 0) return '0B'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

// ─── KPI tile ─────────────────────────────────────────────────────────────────

function KpiTile({ value, label, sub, caveat, color }) {
  return (
    <div className="an__kpi-tile">
      <div className="an__kpi-value" style={color ? { color } : undefined}>{value}</div>
      <div className="an__kpi-label">{label}</div>
      {sub && <div className="an__kpi-sub">{sub}</div>}
      {caveat && <div className="an__kpi-caveat">{caveat}</div>}
    </div>
  )
}

// ─── Ranked card ─────────────────────────────────────────────────────────────

function RankedCard({ title, items, renderItem }) {
  if (!items || items.length === 0) return null
  return (
    <div className="an__ranked-card">
      <div className="an__ranked-card-title">{title}</div>
      {items.map((item, i) => renderItem(item, i))}
    </div>
  )
}

// ─── Active hours histogram ───────────────────────────────────────────────────

function ActiveHoursChart({ data }) {
  if (!data || data.length === 0) return null
  const W = 480, H = 80, BAR_W = (W / 24) - 1
  const max = Math.max(...data.map(d => d.count), 1)

  function hourLabel(h) {
    if (h === 0) return '12a'
    if (h === 12) return '12p'
    if (h < 12) return `${h}a`
    return `${h - 12}p`
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="an__svg" preserveAspectRatio="xMidYMid meet">
      {data.map(({ hour, count }) => {
        const barH = (count / max) * (H - 16)
        const x = hour * (W / 24)
        return (
          <g key={hour}>
            {count > 0 && (
              <rect
                x={x}
                y={H - 16 - barH}
                width={BAR_W}
                height={barH}
                fill="#06b6d4"
                opacity={0.75}
                rx={2}
              />
            )}
            {hour % 6 === 0 && (
              <text
                x={x + BAR_W / 2}
                y={H - 2}
                fontSize="9"
                fill="var(--text-dim)"
                textAnchor="middle"
              >
                {hourLabel(hour)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ─── Tools chart ─────────────────────────────────────────────────────────────

// Single source of truth — drives both color lookup and legend
const TOOL_CATEGORIES = [
  { label: 'File I/O',     color: '#3b82f6', tools: ['Read', 'Write', 'Edit'] },
  { label: 'Search',       color: '#06b6d4', tools: ['Grep', 'Glob'] },
  { label: 'Bash',         color: '#f59e0b', tools: ['Bash'] },
  { label: 'Agent / Task', color: '#8b5cf6', tools: ['Agent', 'Task', 'TaskCreate', 'TaskUpdate', 'TaskGet', 'TaskList', 'TaskOutput', 'TaskStop'] },
  { label: 'Web',          color: '#10b981', tools: ['WebFetch', 'WebSearch'] },
  { label: 'Notebook',     color: '#ec4899', tools: ['NotebookEdit'] },
  { label: 'Plan / Skill', color: '#a855f7', tools: ['Skill', 'ExitPlanMode', 'EnterPlanMode'] },
  { label: 'MCP',          color: '#14b8a6', tools: [], prefix: 'mcp__' },
  { label: 'Other',        color: '#6366f1', tools: [] },
]

// Flat name → color lookup derived from categories
const TOOL_COLOR_MAP = Object.fromEntries(
  TOOL_CATEGORIES.flatMap(c => c.tools.map(t => [t, c.color]))
)

function toolCategory(name) {
  for (const cat of TOOL_CATEGORIES) {
    if (cat.tools.includes(name)) return cat
    if (cat.prefix && name.startsWith(cat.prefix)) return cat
  }
  return TOOL_CATEGORIES[TOOL_CATEGORIES.length - 1]  // Other
}

function toolColor(name) {
  return TOOL_COLOR_MAP[name] ?? toolCategory(name).color
}

function ToolsLegend({ tools }) {
  const presentCats = useMemo(() => {
    const seen = new Set(tools.map(t => toolCategory(t.tool).label))
    return TOOL_CATEGORIES.filter(c => seen.has(c.label))
  }, [tools])

  return (
    <div className="an__tools-legend">
      {presentCats.map(cat => (
        <span key={cat.label} className="an__tools-legend-item">
          <span className="an__tools-legend-swatch" style={{ background: cat.color }} />
          {cat.label}
        </span>
      ))}
    </div>
  )
}

function ToolsChart({ tools }) {
  if (!tools || tools.length === 0) {
    return <div className="an__empty">No tool data in range.</div>
  }
  const total = tools.reduce((s, t) => s + t.count, 0)
  const maxCount = tools[0]?.count || 1   // already sorted desc from backend

  return (
    <div>
      <div className="an__tools-list">
        {tools.map((t, i) => {
          const pct = total > 0 ? (t.count / total * 100).toFixed(1) : '0.0'
          const barPct = (t.count / maxCount * 100).toFixed(2)
          const color = toolColor(t.tool)
          return (
            <div key={t.tool} className="an__tool-row">
              <span className="an__tool-rank">{i + 1}</span>
              <span className="an__tool-name" title={t.tool}>{t.tool}</span>
              <div className="an__tool-bar-track">
                <div
                  className="an__tool-bar-fill"
                  style={{ width: `${barPct}%`, background: color }}
                />
              </div>
              <span className="an__tool-count">{t.count.toLocaleString()}</span>
              <span className="an__tool-pct" style={{ color }}>{pct}%</span>
            </div>
          )
        })}
      </div>
      <ToolsLegend tools={tools} />
    </div>
  )
}

// ─── Model distribution table ─────────────────────────────────────────────────

function ModelTable({ models }) {
  if (!models || models.length === 0) return <div className="an__empty">No sessions in range.</div>
  return (
    <table className="an__model-table">
      <thead>
        <tr>
          <th>Model</th>
          <th>Sessions</th>
          <th>%</th>
          <th>Cost</th>
        </tr>
      </thead>
      <tbody>
        {models.map(m => {
          const ms = modelShort(m.model)
          return (
            <tr key={m.model}>
              <td>
                {ms
                  ? <span className={`model-badge ${ms.cls}`}>{ms.label}</span>
                  : <span>{m.model}</span>}
              </td>
              <td>{m.session_count}</td>
              <td>{m.pct}%</td>
              <td>{fmtCost(m.total_cost_usd)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ─── Memory category breakdown ────────────────────────────────────────────────

function MemoryCategories({ files }) {
  const cats = useMemo(() => {
    const map = {}
    for (const f of files) {
      const cat = (f.path || '').includes('/') ? f.path.split('/')[0] : '.'
      if (!map[cat]) map[cat] = { count: 0, size: 0 }
      map[cat].count++
      map[cat].size += f.size || 0
    }
    return Object.entries(map).sort((a, b) => b[1].count - a[1].count)
  }, [files])

  if (cats.length === 0) return null

  return (
    <div className="an__ranked-card">
      <div className="an__ranked-card-title">By Category</div>
      {cats.map(([cat, data]) => (
        <div key={cat} className="an__ranked-row">
          <span className="an__ranked-name">{cat === '.' ? 'root' : cat}</span>
          <span className="an__ranked-val">{data.count} · {fmtSize(data.size)}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Main Analytics component ─────────────────────────────────────────────────

export default function Analytics({ timeRange }) {
  const [fetchState, setFetchState] = useState({ data: null, loading: true })
  const [memoryTree, setMemoryTree] = useState(null)

  // Fetch analytics; re-fetch when timeRange changes
  useEffect(() => {
    let cancelled = false
    fetch(`/api/analytics?time_range=${timeRange}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setFetchState({ data: d, loading: false }) })
      .catch(() => { if (!cancelled) setFetchState(prev => ({ ...prev, loading: false })) })
    return () => { cancelled = true }
  }, [timeRange])

  // Fetch memory tree once on mount
  useEffect(() => {
    fetch('/api/memory')
      .then(r => r.json())
      .then(setMemoryTree)
      .catch(() => {})
  }, [])

  // Flatten memory tree for analysis
  const allMemoryFiles = useMemo(() => {
    if (!memoryTree) return []
    const flat = []
    function walk(node) {
      if (node.type === 'file') flat.push(node)
      for (const child of (node.children || [])) walk(child)
    }
    walk(memoryTree)
    return flat
  }, [memoryTree])

  const { data: analyticsData, loading } = fetchState

  if (loading) return <div className="an__loading">Loading analytics…</div>
  if (!analyticsData) return <div className="an__loading">No analytics data available.</div>

  const sm = analyticsData.session_metrics

  const totalMemSize = allMemoryFiles.reduce((s, f) => s + (f.size || 0), 0)
  const recentFiles = [...allMemoryFiles]
    .sort((a, b) => (b.mtime || 0) - (a.mtime || 0))
    .slice(0, 5)
  const largestFiles = [...allMemoryFiles]
    .sort((a, b) => (b.size || 0) - (a.size || 0))
    .slice(0, 5)

  return (
    <div className="an">

      {/* ── Sessions Analytics ─────────────────────────────────────────── */}
      <section>
        <div className="an__section-title">Sessions Analytics</div>

        <div className="an__kpi-grid">
          <KpiTile
            value={fmtDuration(sm.total_wall_time_seconds)}
            label="Time Spent"
            sub={sm.sessions_with_duration > 0
              ? `across ${sm.sessions_with_duration} sessions`
              : undefined}
            color="var(--accent)"
          />
          <KpiTile
            value={`${sm.estimated_time_saved_hours}h`}
            label="Est. Time Saved"
            caveat="conservative estimate"
            color="var(--active)"
          />
          <KpiTile
            value={`${sm.cache_efficiency_pct}%`}
            label="Cache Efficiency"
            sub="read / (read + write)"
            color="var(--tokens)"
          />
          <KpiTile
            value={fmtCost(sm.cache_savings_usd)}
            label="Cache Savings"
            sub="vs. full input price"
            color="var(--active)"
          />
          <KpiTile
            value={fmtCost(sm.avg_cost_per_turn)}
            label="Avg Cost / Turn"
            color="var(--cost)"
          />
          <KpiTile
            value={fmt(Math.round(sm.avg_tokens_per_turn))}
            label="Avg Tokens / Turn"
            color="var(--tokens)"
          />
        </div>

        <div className="an__ranked-grid">
          <RankedCard
            title="Longest Sessions"
            items={sm.longest_sessions}
            renderItem={(s, i) => (
              <div key={s.session_id} className="an__ranked-row">
                <span className="an__ranked-num">{i + 1}</span>
                <span className="an__ranked-name" title={s.title}>{s.title}</span>
                <span className="an__ranked-val">{fmtDuration(s.duration_seconds)}</span>
              </div>
            )}
          />
          <RankedCard
            title="Most Expensive Sessions"
            items={sm.most_expensive_sessions}
            renderItem={(s, i) => (
              <div key={s.session_id} className="an__ranked-row">
                <span className="an__ranked-num">{i + 1}</span>
                <span className="an__ranked-name" title={s.title}>{s.title}</span>
                <span className="an__ranked-val">{fmtCost(s.cost_usd)}</span>
              </div>
            )}
          />
          <RankedCard
            title="Most Turns"
            items={sm.most_turns_sessions}
            renderItem={(s, i) => (
              <div key={s.session_id} className="an__ranked-row">
                <span className="an__ranked-num">{i + 1}</span>
                <span className="an__ranked-name" title={s.title}>{s.title}</span>
                <span className="an__ranked-val">{s.turns} turns</span>
              </div>
            )}
          />
          {sm.most_subagents_sessions.length > 0 && (
            <RankedCard
              title="Most Subagents"
              items={sm.most_subagents_sessions}
              renderItem={(s, i) => (
                <div key={s.session_id} className="an__ranked-row">
                  <span className="an__ranked-num">{i + 1}</span>
                  <span className="an__ranked-name" title={s.title}>{s.title}</span>
                  <span className="an__ranked-val">{s.subagent_count} agents</span>
                </div>
              )}
            />
          )}
          <RankedCard
            title="Projects by Activity"
            items={sm.projects_by_sessions}
            renderItem={(p, i) => (
              <div key={p.project_name + i} className="an__ranked-row">
                <span className="an__ranked-num">{i + 1}</span>
                <span className="an__ranked-name" title={p.project_name}>{p.project_name}</span>
                <span className="an__ranked-val">{p.session_count} sessions</span>
              </div>
            )}
          />
          <RankedCard
            title="Projects by Cost"
            items={sm.projects_by_cost}
            renderItem={(p, i) => (
              <div key={p.project_name + i + 'c'} className="an__ranked-row">
                <span className="an__ranked-num">{i + 1}</span>
                <span className="an__ranked-name" title={p.project_name}>{p.project_name}</span>
                <span className="an__ranked-val">{fmtCost(p.total_cost_usd)}</span>
              </div>
            )}
          />
        </div>

        <div className="an__charts-row">
          <div className="an__chart-card">
            <div className="an__chart-title">Model Distribution</div>
            <ModelTable models={sm.model_distribution} />
          </div>
          <div className="an__chart-card">
            <div className="an__chart-title">Active Hours (session start time)</div>
            <ActiveHoursChart data={sm.active_hours} />
          </div>
        </div>

        {sm.top_tools.length > 0 && (
          <div className="an__chart-card">
            <div className="an__chart-title">Top Tools Used (across all sessions in range)</div>
            <ToolsChart tools={sm.top_tools} />
          </div>
        )}
      </section>

      {/* ── Memory Analytics ───────────────────────────────────────────── */}
      <section>
        <div className="an__section-title">Memory Analytics</div>

        <div className="an__kpi-grid">
          <KpiTile
            value={allMemoryFiles.length}
            label="Total Files"
            color="var(--accent)"
          />
          <KpiTile
            value={fmtSize(totalMemSize)}
            label="Total Size"
            color="var(--tokens)"
          />
        </div>

        <div className="an__memory-grid">
          <MemoryCategories files={allMemoryFiles} />

          {recentFiles.length > 0 && (
            <div className="an__ranked-card">
              <div className="an__ranked-card-title">Recently Modified</div>
              {recentFiles.map(f => (
                <div key={f.path} className="an__ranked-row">
                  <span className="an__ranked-name" title={f.path}>{f.name || f.path}</span>
                  <span className="an__ranked-val">{fmtSize(f.size || 0)}</span>
                </div>
              ))}
            </div>
          )}

          {largestFiles.length > 0 && (
            <div className="an__ranked-card">
              <div className="an__ranked-card-title">Largest Files</div>
              {largestFiles.map(f => (
                <div key={f.path + '-sz'} className="an__ranked-row">
                  <span className="an__ranked-name" title={f.path}>{f.name || f.path}</span>
                  <span className="an__ranked-val">{fmtSize(f.size || 0)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

    </div>
  )
}
