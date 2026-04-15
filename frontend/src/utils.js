/**
 * Shared formatter utilities.
 * Components that need these should import from here rather than defining local copies.
 */

export function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

export function fmtCost(n) {
  if (n === 0) return '$0.00'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

/**
 * Returns { label, cls } for a model ID, or null for unknown/empty.
 * `cls` maps to existing badge CSS classes (model-opus, model-sonnet, model-haiku, model-default).
 */
export function modelShort(model) {
  if (!model || model === 'unknown') return null
  if (model.includes('opus'))   return { label: 'Opus',   cls: 'model-opus' }
  if (model.includes('sonnet')) return { label: 'Sonnet', cls: 'model-sonnet' }
  if (model.includes('haiku'))  return { label: 'Haiku',  cls: 'model-haiku' }
  return { label: model.replace('claude-', '').slice(0, 12), cls: 'model-default' }
}
