import './SavingsBanner.css'

function fmtCost(n) {
  if (!n) return '$0.00'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

function fmtTokens(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

const TOOL_ICONS = { Bash: '❯', Read: '📄', WebFetch: '🌐', Grep: '🔍' }

export default function SavingsBanner({ savings, truncation, ollama }) {
  const s = savings || {}
  const t = truncation || {}
  const toolEntries = Object.entries(t.tools || {})

  const hasOllamaActivity = s.pr_skips > 0 || s.summaries_generated > 0
  const hasTruncation = t.total_tokens_saved > 0
  const totalSaved = (s.total_saved_usd ?? 0) + (t.total_cost_saved_usd ?? 0)

  if (!hasOllamaActivity && !hasTruncation && !ollama?.model_ready) return null

  return (
    <div className="savings-banner">

      {/* ── Total saved ── */}
      <div className="savings-left">
        <span className="savings-icon">✦</span>
        <span className="savings-label">Total saved</span>
        <span className="savings-total">{fmtCost(totalSaved)}</span>
      </div>

      {/* ── Ollama section ── */}
      {(hasOllamaActivity || ollama?.model_ready) && (
        <div className="savings-section">
          <span className="savings-section-label">Ollama</span>
          <div className="savings-breakdown">
            <span className="savings-item">
              <span className="savings-count">{s.pr_skips ?? 0}</span>
              <span className="savings-desc">PR{s.pr_skips !== 1 ? 's' : ''} skipped</span>
              <span className="savings-sub">({fmtCost(s.pr_saved_usd ?? 0)})</span>
            </span>
            <span className="savings-sep">·</span>
            <span className="savings-item">
              <span className="savings-count">{s.summaries_generated ?? 0}</span>
              <span className="savings-desc">summaries</span>
              <span className="savings-sub">({fmtCost(s.summary_saved_usd ?? 0)})</span>
            </span>
          </div>
          {s.recent_skips?.length > 0 && (
            <div className="savings-recent">
              {s.recent_skips.slice(-3).reverse().map((sk, i) => (
                <a
                  key={i}
                  className="savings-skip-chip"
                  href={sk.url}
                  target="_blank"
                  rel="noreferrer"
                  title={sk.title}
                >
                  {sk.title?.slice(0, 40) || sk.url}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Truncation hooks section ── */}
      {hasTruncation && (
        <div className="savings-section">
          <span className="savings-section-label">Hooks</span>
          <div className="savings-breakdown">
            {toolEntries.map(([tool, stats], i) => (
              <>
                {i > 0 && <span key={`sep-${i}`} className="savings-sep">·</span>}
                <span key={tool} className="savings-item" title={`${fmtTokens(stats.tokens_saved)} tokens truncated`}>
                  <span className="savings-tool-icon">{TOOL_ICONS[tool] || '⚙'}</span>
                  <span className="savings-count">{stats.count}</span>
                  <span className="savings-desc">{tool}</span>
                  <span className="savings-sub">({fmtCost(stats.cost_saved_usd)})</span>
                </span>
              </>
            ))}
            <span className="savings-sep">·</span>
            <span className="savings-item savings-item-total">
              <span className="savings-count">{fmtTokens(t.total_tokens_saved)}</span>
              <span className="savings-desc">tokens trimmed</span>
            </span>
          </div>
        </div>
      )}

      {/* ── Model status ── */}
      <div className="savings-model">
        <span className={`model-dot ${ollama?.model_ready ? 'dot-ready' : 'dot-off'}`} />
        {ollama?.model || 'no model'}
      </div>

    </div>
  )
}
