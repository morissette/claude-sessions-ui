import './BudgetBanner.css'

export default function BudgetBanner({ status, onDismiss }) {
  const exceeded = []
  if (status.daily?.exceeded)
    exceeded.push(`daily ($${status.daily.spent.toFixed(2)} / $${status.daily.limit.toFixed(2)})`)
  if (status.weekly?.exceeded)
    exceeded.push(`weekly ($${status.weekly.spent.toFixed(2)} / $${status.weekly.limit.toFixed(2)})`)
  if (exceeded.length === 0) return null

  return (
    <div className="budget-banner" role="alert">
      <span className="budget-banner__icon">⚠</span>
      <span className="budget-banner__text">
        Budget exceeded: {exceeded.join(' and ')}
      </span>
      <button className="budget-banner__dismiss" onClick={onDismiss} aria-label="Dismiss budget alert">×</button>
    </div>
  )
}
