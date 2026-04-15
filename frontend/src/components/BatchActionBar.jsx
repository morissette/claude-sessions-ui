import './BatchActionBar.css'

export default function BatchActionBar({ count, onSelectAll, onDeselectAll, onSummarize, onExport, onCostReport, ollamaAvailable }) {
  if (count === 0) return null
  return (
    <div className="batch-action-bar">
      <span className="batch-action-bar__count">{count} selected</span>
      <button type="button" className="batch-action-bar__ctrl" onClick={onSelectAll}>All</button>
      <button type="button" className="batch-action-bar__ctrl" onClick={onDeselectAll}>None</button>
      <div className="batch-action-bar__actions">
        <button
          type="button"
          className="batch-action-bar__btn"
          onClick={onSummarize}
          disabled={!ollamaAvailable}
          title={!ollamaAvailable ? 'Ollama not available' : 'Summarize selected sessions'}
        >
          Summarize
        </button>
        <button type="button" className="batch-action-bar__btn" onClick={onExport}>Export ZIP</button>
        <button type="button" className="batch-action-bar__btn" onClick={onCostReport}>Cost CSV</button>
      </div>
    </div>
  )
}
