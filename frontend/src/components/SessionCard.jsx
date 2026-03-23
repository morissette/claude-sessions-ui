import { useMemo, useState, useCallback } from 'react'
import './SessionCard.css'

function timeAgo(isoStr) {
  if (!isoStr) return ''
  const diff = Date.now() - new Date(isoStr).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function fmtCost(n) {
  if (n === 0) return '$0.00'
  if (n < 0.0001) return '<$0.0001'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(3)}`
}

function modelShort(model) {
  if (!model || model === 'unknown') return null
  if (model.includes('opus')) return { label: 'Opus', cls: 'model-opus' }
  if (model.includes('sonnet')) return { label: 'Sonnet', cls: 'model-sonnet' }
  if (model.includes('haiku')) return { label: 'Haiku', cls: 'model-haiku' }
  return { label: model.replace('claude-', '').slice(0, 12), cls: 'model-default' }
}

function agentTypeLabel(type) {
  const map = {
    'general-purpose': 'General',
    'Explore': 'Explore',
    'Plan': 'Plan',
    'test-runner': 'Tests',
    'code-fixer': 'Fix',
    'security-auditor': 'Security',
    'bug-auditor': 'Bugs',
  }
  return map[type] || type?.replace(/-/g, ' ') || 'Agent'
}

function TokenBar({ stats }) {
  const total = stats.input_tokens + stats.output_tokens + stats.cache_create_tokens + stats.cache_read_tokens
  if (total === 0) return null
  const pct = (n) => `${((n / total) * 100).toFixed(1)}%`
  return (
    <div className="token-bar-wrap">
      <div className="token-bar">
        <div className="tb-seg tb-input"   style={{ width: pct(stats.input_tokens) }}         title={`Input: ${fmt(stats.input_tokens)}`} />
        <div className="tb-seg tb-output"  style={{ width: pct(stats.output_tokens) }}        title={`Output: ${fmt(stats.output_tokens)}`} />
        <div className="tb-seg tb-ccreate" style={{ width: pct(stats.cache_create_tokens) }}  title={`Cache write: ${fmt(stats.cache_create_tokens)}`} />
        <div className="tb-seg tb-cread"   style={{ width: pct(stats.cache_read_tokens) }}    title={`Cache read: ${fmt(stats.cache_read_tokens)}`} />
      </div>
      <div className="token-legend">
        <span className="tl-item"><span className="tl-dot tl-input" />input {fmt(stats.input_tokens)}</span>
        <span className="tl-item"><span className="tl-dot tl-output" />output {fmt(stats.output_tokens)}</span>
        <span className="tl-item"><span className="tl-dot tl-cread" />cached {fmt(stats.cache_read_tokens)}</span>
      </div>
    </div>
  )
}

export default function SessionCard({ session, ollama }) {
  const [summary, setSummary] = useState(session.ai_summary || null)
  const [summarizing, setSummarizing] = useState(false)

  const summarize = useCallback(async () => {
    if (summarizing || summary) return
    setSummarizing(true)
    try {
      const r = await fetch(`/api/sessions/${session.session_id}/summarize`, { method: 'POST' })
      const d = await r.json()
      if (d.summary) setSummary(d.summary)
    } catch {}
    setSummarizing(false)
  }, [session.session_id, summarizing, summary])

  const model = useMemo(() => modelShort(session.model), [session.model])
  const ago = useMemo(() => timeAgo(session.last_active), [session.last_active])
  const active = session.is_active

  // Shorten path: show last 2–3 components
  const shortPath = useMemo(() => {
    const parts = (session.project_path || '').split('/').filter(Boolean)
    return parts.slice(-3).join(' / ')
  }, [session.project_path])

  return (
    <div className={`session-card ${active ? 'card-active' : 'card-idle'}`}>
      {/* top accent bar */}
      <div className={`card-accent-bar ${active ? 'bar-active' : 'bar-idle'}`} />

      {/* header row */}
      <div className="card-header">
        <div className="card-header-left">
          <div className={`status-dot ${active ? 'dot-active' : 'dot-idle'}`} />
          <span className="project-name">{session.project_name}</span>
          {session.git_branch && (
            <span className="branch-tag mono">{session.git_branch}</span>
          )}
        </div>
        <div className="card-header-right">
          <span className="time-ago">{ago}</span>
          {active && session.pid && (
            <span className="pid-tag mono">PID {session.pid}</span>
          )}
        </div>
      </div>

      {/* project path */}
      <div className="card-path mono">{shortPath}</div>

      {/* title */}
      <div className="card-title-row">
        <div className="card-title">
          {summary
            ? <><span className="ai-summary-tag">✦</span> {summary}</>
            : session.title}
        </div>
        {ollama?.model_ready && !summary && (
          <button
            className={`summarize-btn ${summarizing ? 'summarizing' : ''}`}
            onClick={summarize}
            disabled={summarizing}
            title={`Summarize with ${ollama.model}`}
          >
            {summarizing ? '…' : '✦'}
          </button>
        )}
      </div>

      {/* current activity (only if active) */}
      {active && session.last_activity && (
        <div className="card-activity">
          <span className="activity-label">▶</span>
          <span className="activity-text">{session.last_activity}</span>
        </div>
      )}

      {/* badges row */}
      <div className="card-badges">
        {model && (
          <span className={`badge ${model.cls}`}>
            {model.label}
          </span>
        )}
        {session.subagent_count > 0 && (
          <span className="badge badge-agents">
            ⚡ {session.subagent_count} subagent{session.subagent_count !== 1 ? 's' : ''}
          </span>
        )}
        {session.turns > 0 && (
          <span className="badge badge-turns">
            {session.turns} turn{session.turns !== 1 ? 's' : ''}
          </span>
        )}
        {session.compact_potential_usd > 0.005 && (
          <span
            className="badge badge-compact"
            title={`~$${session.compact_potential_usd.toFixed(3)} savings over next 10 turns — run /compact to shrink context`}
          >
            ⚡ /compact
          </span>
        )}
        <span className={`badge ${active ? 'badge-active-status' : 'badge-idle-status'}`}>
          {active ? 'Active' : 'Idle'}
        </span>
      </div>

      {/* subagent list */}
      {session.subagents?.length > 0 && (
        <div className="subagent-list">
          {session.subagents.map(a => (
            <span key={a.id} className="subagent-chip">
              {agentTypeLabel(a.agent_type)}
            </span>
          ))}
        </div>
      )}

      {/* token bar */}
      <TokenBar stats={session.stats} />

      {/* cost row */}
      <div className="card-cost-row">
        <div className="cost-block">
          <span className="cost-label">Cost</span>
          <span className="cost-value mono">{fmtCost(session.stats.estimated_cost_usd)}</span>
        </div>
        <div className="cost-block">
          <span className="cost-label">Total tokens</span>
          <span className="cost-value mono tokens-color">{fmt(session.stats.total_tokens)}</span>
        </div>
        <div className="cost-block">
          <span className="cost-label">Cache saved</span>
          <span className="cost-value mono cache-color">
            {fmt(session.stats.cache_read_tokens)}
          </span>
        </div>
      </div>

      {/* session id */}
      <div className="session-id-row">
        <span className="session-id mono">{session.session_id.slice(0, 8)}…</span>
      </div>
    </div>
  )
}
