import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import ProjectCard from '../components/ProjectCard'

const proj = {
  project_name: 'my-project',
  project_path: '/home/user/my-project',
  session_count: 3,
  total_cost_usd: 1.23,
  total_tokens: 5000,
  active_sessions: 1,
  last_session: '2026-04-15T10:00:00',
  models: ['claude-sonnet-4-6'],
}

describe('ProjectCard', () => {
  it('renders project name', () => {
    render(<ProjectCard project={proj} onSelect={() => {}} />)
    expect(screen.getByText('my-project')).toBeInTheDocument()
  })

  it('calls onSelect with the project when clicked', () => {
    const onSelect = vi.fn()
    render(<ProjectCard project={proj} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledWith(proj)
  })
})
