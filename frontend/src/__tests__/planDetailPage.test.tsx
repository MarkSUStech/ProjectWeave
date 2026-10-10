/** 详情页学习路线渲染测试（mock API 模块，独立文件避免 vi.mock 提升污染）。 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PlanDetail } from '../types/plan'

vi.mock('../api/projects', () => ({
  getProject: vi.fn().mockResolvedValue({
    id: 'p1', ownerId: 'dev-user', title: '路线项目', description: '',
    mode: 'rebuild', status: 'draft', complexity: 'small',
    targetFeatures: [], nonGoals: [], stack: ['TypeScript'],
    milestones: [], acceptanceCriteria: [], specVersion: 1,
    createdAt: 't', updatedAt: 't',
  }),
}))
vi.mock('../api/files', () => ({
  getCodeVersion: vi.fn().mockResolvedValue({ codeVersion: 'sha256:x', fileCount: 3 }),
  listFiles: vi.fn().mockResolvedValue([]),
}))
vi.mock('../lib/runner/runTestSuite', () => ({
  runTestSuite: vi.fn(),
}))
vi.mock('../api/assessments', () => ({
  listProjectAssessments: vi.fn().mockResolvedValue([]),
}))
vi.mock('../api/plans', () => ({
  getPlan: vi.fn(),
  replan: vi.fn(),
}))

const { getPlan } = await import('../api/plans')
const mockedPlan = vi.mocked(getPlan)
const { default: ProjectDetailPage } = await import('../pages/ProjectDetailPage')

const detail: PlanDetail = {
  plan: {
    id: '4e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
    projectId: 'p1',
    planVersion: 2,
    activities: [
      {
        type: 'learn-concept',
        order: 1,
        conceptId: 'js.closures',
        taskId: 'task-input',
        title: null,
        reason: '先修补课，估计偏低（0.5）',
      },
      {
        type: 'practice-task',
        order: 2,
        conceptId: null,
        taskId: 'task-scaffold',
        title: '建立页面骨架',
        reason: '里程碑 M1 交付：可打开的编辑器布局页面',
      },
    ],
    skipped: [{ conceptId: 'js.values-types', reason: '已掌握（估计 1.0，2 条证据）' }],
    reason: '基于学习证据生成（累计 16 条；掌握阈值 0.75 / 置信阈值 0.5）',
    createdAt: '2026-10-10T10:00:00Z',
  },
  tasks: [{ taskId: 'task-scaffold', milestone: 1, title: '建立页面骨架', status: 'pending' }],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ProjectDetailPage 学习路线', () => {
  it('显示活动、原因、跳过项与版本', async () => {
    mockedPlan.mockResolvedValue(detail)
    render(
      <MemoryRouter initialEntries={['/projects/p1']}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('学习路线')).toBeTruthy()
    expect(screen.getByText(/js\.closures/)).toBeTruthy()
    expect(screen.getByText(/先修补课，估计偏低/)).toBeTruthy()
    expect(screen.getByText(/路线 v2/)).toBeTruthy()
    expect(screen.getByText(/已跳过 1 个概念/)).toBeTruthy()
    expect(screen.getByText('↻ 重新规划')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('M1')).toBeTruthy())
  })

  it('plan 加载失败显示错误但不阻塞项目信息', async () => {
    mockedPlan.mockRejectedValue(new Error('down'))
    render(
      <MemoryRouter initialEntries={['/projects/p1']}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('路线项目')).toBeTruthy()
    expect(await screen.findByText(/学习路线加载失败/)).toBeTruthy()
  })
})
