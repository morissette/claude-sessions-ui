import { useState, useEffect, useCallback } from 'react'
import SessionAnalytics from './SessionAnalytics'
import './SessionDetail.css'

// ─── System message helpers ───────────────────────────────────────────────────

/** True if content consists entirely of XML-like system tags (no free text outside). */
function isSystemContent(content) {
  if (typeof content !== 'string' || !content.trim()) return false
  return /^[\s]*(<[a-z][a-z0-9-]*>[\s\S]*?<\/[a-z][a-z0-9-]*>\s*)+$/.test(content)
}

/** Extract inner text of a named tag, or null. */
function parseSystemTag(content, tag) {
  const m = content.match(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`))
  return m ? m[1].trim() : null
}

/**
 * Classify a system message. Returns { kind, ...data }.
 * Add new tag types here as the library grows.
 */
const KNOWN_TAGS = {
  'local-command-caveat': () => ({ kind: 'caveat' }),
  'command-name': (c) => ({
    kind: 'command',
    name: parseSystemTag(c, 'command-name'),
    message: parseSystemTag(c, 'command-message'),
    args: parseSystemTag(c, 'command-args'),
  }),
  'local-command-stdout': (c) => ({
    kind: 'stdout',
    text: parseSystemTag(c, 'local-command-stdout'),
  }),
  'system-reminder': () => ({ kind: 'reminder' }),
}

function classifySystemMessage(content) {
  for (const [tag, fn] of Object.entries(KNOWN_TAGS)) {
    if (content.includes(`<${tag}>`)) return fn(content)
  }
  return { kind: 'unknown' }
}

/** Collapse adjacent system user messages into groups. Normal messages pass through. */
function groupMessages(messages) {
  const result = []
  let i = 0
  while (i < messages.length) {
    const msg = messages[i]
    if (msg.type === 'user' && isSystemContent(msg.content)) {
      const group = []
      while (i < messages.length && messages[i].type === 'user' && isSystemContent(messages[i].content)) {
        group.push(messages[i])
        i++
      }
      result.push({ __systemGroup: true, messages: group, key: group[0].id })
    } else {
      result.push(msg)
      i++
    }
  }
  return result
}

/** Replace [Image: source: /path] markers with inline <img> thumbnails. */
function renderContentWithImages(content) {
  if (typeof content !== 'string') return content
  const matches = [...content.matchAll(/\[Image:\s*source:\s*([^\]]+?)\]/g)]
  if (matches.length === 0) return content

  const parts = []
  let last = 0
  for (const m of matches) {
    if (m.index > last) parts.push(content.slice(last, m.index))
    const filePath = m[1].trim()
    const src = `/api/image-proxy?path=${encodeURIComponent(filePath)}`
    parts.push(
      <img
        key={m.index}
        src={src}
        className="msg-image-thumb"
        alt={filePath.split('/').pop()}
        onError={e => {
          const img = e.target
          img.style.display = 'none'
          const span = document.createElement('span')
          span.className = 'msg-image-unavailable'
          span.textContent = `[${img.alt}]`
          img.parentNode.insertBefore(span, img.nextSibling)
        }}
      />
    )
    last = m.index + m[0].length
  }
  if (last < content.length) parts.push(content.slice(last))
  return parts
}

// ─── System pin ───────────────────────────────────────────────────────────────

function SystemPin({ group }) {
  let cmdName = null, args = null, stdout = null, hasContent = false

  for (const msg of group.messages) {
    const info = classifySystemMessage(msg.content)
    if (info.kind === 'command') {
      cmdName = info.name
      args = info.args || info.message
      hasContent = true
    }
    if (info.kind === 'stdout' && info.text) { stdout = info.text; hasContent = true }
    if (info.kind === 'unknown') { hasContent = true }
  }

  // caveat/reminder-only groups: render nothing
  if (!hasContent) return null

  const icon = cmdName ? '⚡' : '⚙'
  const detail = stdout
    ? (stdout.length > 60 ? stdout.slice(0, 60) + '…' : stdout)
    : args
      ? (args.length > 60 ? args.slice(0, 60) + '…' : args)
      : null
  const text = [cmdName, detail].filter(Boolean).join(' · ') || 'system context'

  return (
    <div className="msg-command-pin">
      <span className="msg-command-pin__badge">{icon} {text}</span>
    </div>
  )
}

// ─── Message thread ───────────────────────────────────────────────────────────

function MessageThread({ messages }) {
  if (messages.length === 0) {
    return <div className="detail-empty">No messages in this session</div>
  }

  const items = []
  let prevRole = null

  groupMessages(messages).forEach((item, i) => {
    if (item.__systemGroup) {
      const pin = <SystemPin key={`sys-${item.key}`} group={item} />
      if (pin) items.push(pin)
      // pins don't update prevRole — they sit between messages without breaking divider logic
      return
    }

    const msg = item
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
            <div className="msg-text">{renderContentWithImages(msg.content)}</div>
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
            <div className="msg-text">{renderContentWithImages(msg.content)}</div>
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
  const [analyticsError, setAnalyticsError] = useState(null)

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

  // Reset analytics state when the session changes so stale data from the
  // previous session is not shown while the new session loads.
  useEffect(() => {
    setActiveTab('transcript')
    setAnalyticsData(null)
    setAnalyticsError(null)
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
    if (analyticsData) return  // already loaded for this session
    setAnalyticsLoading(true)
    setAnalyticsError(null)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/analytics`)
      if (res.ok) {
        setAnalyticsData(await res.json())
      } else {
        setAnalyticsError(`Failed to load analytics (${res.status})`)
      }
    } catch {
      setAnalyticsError('Failed to load analytics')
    }
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
            <>
              {analyticsError && <div className="detail-error">{analyticsError}</div>}
              <SessionAnalytics data={analyticsData} loading={analyticsLoading} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
