import './SearchResults.css'

/**
 * Sanitize a raw FTS snippet for safe HTML injection.
 * 1. HTML-escape the raw text to neutralize any tags or event handlers.
 * 2. Convert **term** markers (added by SQLite snippet()) to <mark> elements.
 */
function renderSnippet(raw) {
  const escaped = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
  return escaped.replace(/\*\*(.*?)\*\*/g, '<mark>$1</mark>')
}

export default function SearchResults({ results, loading, onSelect }) {
  if (loading) return <div className="search-results__loading">Searching…</div>

  if (!results) return null

  return (
    <div className="search-results">
      {!results.index_ready && (
        <div className="search-results__notice">Building search index… results may be partial.</div>
      )}
      {results.results.length === 0 ? (
        <div className="search-results__empty">No results for &ldquo;{results.query}&rdquo;</div>
      ) : (
        <>
          <div className="search-results__count">{results.total} result{results.total !== 1 ? 's' : ''}</div>
          <ul className="search-results__list">
            {results.results.map((r, i) => (
              <li key={`${r.session_id}-${i}`} className="search-result">
                <button type="button" onClick={() => onSelect(r.session_id)}>
                  <div className="search-result__header">
                    <span className="search-result__title">{r.session_title || r.session_id}</span>
                    <span className="search-result__project">{r.project_name}</span>
                    <span className={`search-result__role search-result__role--${r.role}`}>{r.role}</span>
                  </div>
                  <div
                    className="search-result__snippet"
                    dangerouslySetInnerHTML={{ __html: renderSnippet(r.snippet) }}
                  />
                  <div className="search-result__ts">{r.ts}</div>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
