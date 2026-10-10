/** 仪表盘页面组件测试：列表渲染与空状态。 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import DashboardPage from '../pages/DashboardPage'
import type { Project } from '../types/project'

vi.mock('../api/projects', () => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
}))

const { listProjects } = await import('../api/projects')
const mockedListProjects = vi.mocked(listProjects)

const fixture: Project = {
  id: '0e0f26b4-7e4d-4c8f-9d3a-2f4f5c6a7b8d',
  ownerId: 'dev-user',
  title: 'Markdown 笔记编辑器',
  description: '带实时预览的笔记应用',
  mode: 'rebuild',
  status: 'draft',
  complexity: 'medium',
  targetFeatures: [],
  nonGoals: [],
  stack: ['TypeScript'],
  milestones: [],
  acceptanceCriteria: [],
  specVersion: 1,
  createdAt: '2026-10-10T03:00:00Z',
  updatedAt: '2026-10-10T03:00:00Z',
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

describe('DashboardPage', () => {
  it('加载并渲染项目卡片', async () => {
    mockedListProjects.mockResolvedValue([fixture])
    renderDashboard()
    expect(await screen.findByText('Markdown 笔记编辑器')).toBeTruthy()
    expect(screen.getByText('从零重建')).toBeTruthy()
  })

  it('项目为空时展示空状态', async () => {
    mockedListProjects.mockResolvedValue([])
    renderDashboard()
    expect(await screen.findByText('还没有项目')).toBeTruthy()
  })

  it('加载失败时展示错误与重试', async () => {
    mockedListProjects.mockRejectedValue(new Error('boom'))
    renderDashboard()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('重试')).toBeTruthy()
  })
})
