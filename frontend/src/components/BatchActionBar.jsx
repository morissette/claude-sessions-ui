import './BatchActionBar.css'

export default function BatchActionBar({ count, onSelectAll, onDeselectAll, onSummarize, onExport, onCostReport, ollamaAvailable }) {
  return (
    <div className="batch-action-bar">
      <span className="batch-action-bar__count">{count} selected</span>
      <button type="button" className="batch-action-bar__ctrl" onClick={onSelectAll}>All</button>
      <button type="button" className="batch-action-bar__ctrl" onClick={onDeselectAll} disabled={count === 0}>None</button>
      <div className="batch-action-bar__actions">
        <button
          type="button"
          className="batch-action-bar__btn"
          onClick={onSummarize}
          disabled={!ollamaAvailable || count === 0}
          title={!ollamaAvailable ? 'Ollama not available' : count === 0 ? 'Select sessions first' : 'Summarize selected sessions'}
        >
          Summarize
        </button>
        <button type="button" className="batch-action-bar__btn" onClick={onExport} disabled={count === 0}>Export ZIP</button>
        <button type="button" className="batch-action-bar__btn" onClick={onCostReport} disabled={count === 0}>Cost CSV</button>
      </div>
    </div>
  )
}
