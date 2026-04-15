import { useState, useEffect } from 'react'
import './SessionDetail.css'

function MessageThread({ messages }) {
  if (messages.length === 0) {
    return <div className="detail-empty">No messages</div>
  }
  return messages.map((msg, i) => {
    if (msg.type === 'user') {
      return (
        <div key={i} className="msg-user">
          {msg.timestamp && <span className="msg-ts">{new Date(msg.timestamp).toLocaleTimeString()}</span>}
          <div className="msg-text">{msg.content}</div>
        </div>
      )
    }
    if (msg.type === 'assistant') {
      return (
        <div key={i} className="msg-assistant">
          {msg.timestamp && <span className="msg-ts">{new Date(msg.timestamp).toLocaleTimeString()}</span>}
          {msg.thinking && (
            <details className="msg-thinking">
              <summary>Thinking</summary>
              <pre className="msg-pre">{msg.thinking}</pre>
            </details>
          )}
          <div className="msg-text">{msg.content}</div>
        </div>
      )
    }
    if (msg.type === 'tool_use') {
      return (
        <details key={i} className="msg-tool">
          <summary className="msg-tool-summary">
            <span className="tool-label">Tool</span>
            <span className="tool-name">{msg.tool_name || 'unknown'}</span>
          </summary>
          <pre className="msg-pre">{msg.content}</pre>
        </details>
      )
    }
    if (msg.type === 'tool_result') {
      return (
        <details key={i} className="msg-tool msg-tool-result">
          <summary className="msg-tool-summary">
            <span className="tool-label">Result</span>
            <span className="tool-name">{msg.tool_name || 'unknown'}</span>
          </summary>
          <pre className="msg-pre">{msg.content}</pre>
        </details>
      )
    }
    if (msg.type === 'summary') {
      return (
        <div key={i} className="msg-summary">
          {msg.content}
        </div>
      )
    }
    return null
  })
}

export default function SessionDetail({ sessionId, onClose }) {
  // State is initialized fresh on each mount — parent passes key={sessionId} to remount on change
  const [fetchState, setFetchState] = useState({ loading: true, error: null, detail: null, offset: 0 })
  const { loading, error, detail, offset } = fetchState
  const limit = 200

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

  const hasMore = detail && (offset + limit) < detail.total_messages

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <div className="detail-header">
          <h2 className="detail-title">Session Detail</h2>
          <button className="detail-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="detail-body">
          {loading && <div className="detail-loading">Loading…</div>}
          {error && <div className="detail-error">{error}</div>}
          {detail && <MessageThread messages={detail.messages} />}
          {hasMore && (
            <button className="detail-load-more" onClick={loadMore}>
              Load more ({detail.total_messages - offset - limit} remaining)
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
