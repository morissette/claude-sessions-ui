import './ProjectCard.css'

function modelShort(model) {
  if (!model || model === 'unknown') return null
  if (model.includes('opus')) return { label: 'Opus', cls: 'model-opus' }
  if (model.includes('sonnet')) return { label: 'Sonnet', cls: 'model-sonnet' }
  if (model.includes('haiku')) return { label: 'Haiku', cls: 'model-haiku' }
  return { label: model.replace('claude-', '').slice(0, 12), cls: 'model-default' }
}

export default function ProjectCard({ project, onSelect }) {
  const {
    project_name,
    project_path,
    session_count,
    total_cost_usd,
    total_tokens,
    models,
  } = project

  return (
    <button
      type="button"
      className="project-card"
      onClick={() => onSelect(project)}
    >
      <div className="project-card__header">
        <span className="project-card__name">{project_name}</span>
        <span className="project-card__cost">${total_cost_usd.toFixed(4)}</span>
      </div>
      <div className="project-card__path">{project_path}</div>
      <div className="project-card__meta">
        <span>{session_count} session{session_count !== 1 ? 's' : ''}</span>
        <span>{(total_tokens / 1000).toFixed(1)}K tokens</span>
      </div>
      <div className="project-card__models">
        {models.map(m => {
          const ms = modelShort(m)
          return ms
            ? <span key={m} className={`model-badge badge ${ms.cls}`}>{ms.label}</span>
            : <span key={m} className="model-badge badge model-default">{m}</span>
        })}
      </div>
    </button>
  )
}

export function ProjectList({ projects, onSelect }) {
  if (projects.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">◇</div>
        <p className="empty-title">No projects found</p>
        <p className="empty-sub">No projects found for this time range.</p>
      </div>
    )
  }
  return (
    <div className="project-list">
      {projects.map(p => (
        <ProjectCard
          key={p.project_path || p.project_name}
          project={p}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}
