import { useState, useEffect, useCallback } from 'react'
import SessionAnalytics from './SessionAnalytics'
import './SessionDetail.css'

function MessageThread({ messages }) {
  if (messages.length === 0) {
    return <div className="detail-empty">No messages in this session</div>
  }

  const items = []
  let prevRole = null

  messages.forEach((msg, i) => {
    const role =
      msg.type === 'user' ? 'user'
      : msg.type === 'assistant' ? 'assistant'
      : msg.type === 'tool_use' ? 'tool'
      : msg.type === 'tool_result' ? 'result'
      : msg.type === 'summary' ? 'summary'
      : null

    if (
      prevRole !== null &&
      role !== prevRole &&
      !(prevRole === 'tool' && role === 'result')
    ) {
      items.push(<div key={`div-${i}`} className="msg-divider" />)
    }
    prevRole = role

    if (msg.type === 'user') {
      items.push(
        <div key={i} className="msg-group">
          <span className="msg-role-label msg-role-label--user">You</span>
          <div className="msg-user">
            {msg.timestamp && (
              <span className="msg-ts">{new Date(msg.timestamp).toLocaleTimeString()}</span>
            )}
            <div className="msg-text">{msg.content}</div>
          </div>
        </div>
      )
    } else if (msg.type === 'assistant') {
      items.push(
        <div key={i} className="msg-group">
          <span className="msg-role-label msg-role-label--assistant">Claude</span>
          <div className="msg-assistant">
            {msg.timestamp && (
              <span className="msg-ts">{new Date(msg.timestamp).toLocaleTimeString()}</span>
            )}
            {msg.thinking && (
              <details className="msg-thinking">
                <summary>Extended thinking</summary>
                <pre className="msg-pre">{msg.thinking}</pre>
              </details>
            )}
            <div className="msg-text">{msg.content}</div>
          </div>
        </div>
      )
    } else if (msg.type === 'tool_use') {
      items.push(
        <details key={i} className="msg-tool">
          <summary className="msg-tool-summary">
            <span className="tool-label">Tool</span>
            <span className="tool-name">{msg.tool_name || 'unknown'}</span>
          </summary>
          <pre className="msg-pre">{msg.content}</pre>
        </details>
      )
    } else if (msg.type === 'tool_result') {
      items.push(
        <details key={i} className="msg-tool msg-tool-result">
          <summary className="msg-tool-summary">
            <span className="tool-label">Result</span>
            <span className="tool-name">{msg.tool_name || 'unknown'}</span>
          </summary>
          <pre className="msg-pre">{msg.content}</pre>
        </details>
      )
    } else if (msg.type === 'summary') {
      items.push(
        <div key={i} className="msg-summary">
          {msg.content}
        </div>
      )
    }
  })

  return <>{items}</>
}

export default function SessionDetail({ sessionId, onClose }) {
  const [fetchState, setFetchState] = useState({ loading: true, error: null, detail: null, offset: 0 })
  const { loading, error, detail, offset } = fetchState
  const limit = 200

  const [activeTab, setActiveTab] = useState('transcript')
  const [analyticsData, setAnalyticsData] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)

  const [exportScope, setExportScope] = useState('global')
  const [exportState, setExportState] = useState('idle')
  const [exportedName, setExportedName] = useState('')
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    fetch(`/api/sessions/${sessionId}/detail?limit=${limit}`)
      .then(r => r.json())
      .then(d => setFetchState(prev => ({ ...prev, loading: false, detail: d })))
      .catch(e => setFetchState(prev => ({ ...prev, loading: false, error: e.message })))
  }, [sessionId])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  function loadMore() {
    const nextOffset = offset + limit
    fetch(`/api/sessions/${sessionId}/detail?offset=${nextOffset}&limit=${limit}`)
      .then(r => r.json())
      .then(d => setFetchState(prev => ({
        ...prev,
        detail: { ...prev.detail, messages: [...(prev.detail?.messages || []), ...d.messages] },
        offset: nextOffset,
      })))
      .catch(() => {})
  }

  async function fetchAnalytics() {
    if (analyticsData) return  // already loaded
    setAnalyticsLoading(true)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/analytics`)
      if (res.ok) setAnalyticsData(await res.json())
    } catch { /* degrade gracefully */ }
    setAnalyticsLoading(false)
  }

  const handleExportSkill = useCallback(async () => {
    setExportState('loading')
    try {
      const res = await fetch(
        `/api/sessions/${sessionId}/export-skill?scope=${exportScope}`,
        { method: 'POST' }
      )
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setExportedName(data.skill_name)
      setExportState('done')
    } catch {
      setExportState('error')
    }
  }, [sessionId, exportScope])

  const handleDownloadTranscript = useCallback(async () => {
    setDownloading(true)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/transcript`)
      if (!res.ok) throw new Error('Failed to fetch transcript')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `claude-session-${sessionId.slice(0, 8)}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {}
    setDownloading(false)
  }, [sessionId])

  const hasMore = detail && (offset + limit) < detail.total_messages
  const shortId = sessionId.slice(0, 8)
  const totalCount = detail?.total_messages ?? 0

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>

        {/* ── Header ── */}
        <div className="detail-header">
          <div className="detail-header-left">
            <h2 className="detail-title">Session Detail</h2>
            <span className="detail-subtitle">
              {shortId}… {totalCount > 0 ? `· ${totalCount} messages` : ''}
            </span>
          </div>
          <div className="detail-header-actions">
            <button
              className={`detail-action-btn ${downloading ? 'detail-action-btn--loading' : ''}`}
              onClick={handleDownloadTranscript}
              disabled={downloading || loading}
              title="Download transcript as Markdown"
            >
              {downloading ? '…' : '↓ Transcript'}
            </button>
            <button className="detail-close" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>

        {/* ── Export as skill (moved from card) ── */}
        <div className="detail-skill-row" onClick={e => e.stopPropagation()}>
          <span className="detail-skill-label">Export as skill</span>
          <select
            className="detail-skill-scope"
            value={exportScope}
            onChange={e => setExportScope(e.target.value)}
            disabled={exportState === 'loading'}
          >
            <option value="global">Global</option>
            <option value="local">Local</option>
          </select>
          <button
            className={`detail-skill-btn detail-skill-btn--${exportState}`}
            disabled={exportState === 'loading' || exportState === 'done'}
            onClick={handleExportSkill}
          >
            {exportState === 'idle' && 'Export'}
            {exportState === 'loading' && 'Exporting…'}
            {exportState === 'done' && `✓ /${exportedName}`}
            {exportState === 'error' && 'Retry'}
          </button>
        </div>

        {/* ── Tabs ── */}
        <div className="session-detail__tabs">
          <button
            className={`session-detail__tab ${activeTab === 'transcript' ? 'session-detail__tab--active' : ''}`}
            onClick={() => setActiveTab('transcript')}
          >Transcript</button>
          <button
            className={`session-detail__tab ${activeTab === 'analytics' ? 'session-detail__tab--active' : ''}`}
            onClick={() => { setActiveTab('analytics'); fetchAnalytics() }}
          >Analytics</button>
        </div>

        {/* ── Body ── */}
        <div className="detail-body">
          {activeTab === 'transcript' && (
            <>
              {loading && <div className="detail-loading">Loading messages</div>}
              {error && <div className="detail-error">{error}</div>}
              {detail && <MessageThread messages={detail.messages} />}
              {hasMore && (
                <button className="detail-load-more" onClick={loadMore}>
                  Load more · {detail.total_messages - offset - limit} remaining
                </button>
              )}
            </>
          )}
          {activeTab === 'analytics' && (
            <SessionAnalytics data={analyticsData} loading={analyticsLoading} />
          )}
        </div>
      </div>
    </div>
  )
}
