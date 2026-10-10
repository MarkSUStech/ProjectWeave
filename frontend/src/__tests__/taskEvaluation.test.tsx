/** 详情页阶段验收流程测试（mock 依赖模块；API 客户端测试在独立文件）。 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PlanDetail } from '../types/plan'

vi.mock('../api/projects', () => ({
  getProject: vi.fn().mockResolvedValue({
    id: 'p1', ownerId: 'dev-user', title: '验收项目', description: '',
    mode: 'rebuild', status: 'draft', complexity: 'small',
    targetFeatures: [], nonGoals: [], stack: ['TypeScript'],
    milestones: [], acceptanceCriteria: [], specVersion: 1,
    createdAt: 't', updatedAt: 't',
  }),
}))
vi.mock('../api/files', () => ({
  getCodeVersion: vi.fn().mockResolvedValue({ codeVersion: 'sha256:x', fileCount: 3 }),
  listFiles: vi.fn().mockResolvedValue([
    { path: 'src/main.test.ts', size: 10, updatedAt: 't' },
  ]),
}))
vi.mock('../api/assessments', () => ({
  listProjectAssessments: vi.fn().mockResolvedValue([]),
}))
vi.mock('../api/plans', () => ({
  getPlan: vi.fn(),
  replan: vi.fn(),
}))
vi.mock('../api/tasks', () => ({
  evaluateTask: vi.fn(),
}))
vi.mock('../lib/runner/runTestSuite', () => ({
  runTestSuite: vi.fn(),
}))
vi.mock('../stores/runStore', () => ({
  useRunStore: Object.assign(vi.fn(), {
    getState: () => ({ trace: { traceId: 'trace-1' } }),
  }),
}))

const { getPlan } = await import('../api/plans')
const mockedPlan = vi.mocked(getPlan)
const { evaluateTask } = await import('../api/tasks')
const mockedEvaluate = vi.mocked(evaluateTask)
const { runTestSuite } = await import('../lib/runner/runTestSuite')
const mockedRunSuite = vi.mocked(runTestSuite)
const { default: ProjectDetailPage } = await import('../pages/ProjectDetailPage')

function planDetail(taskStatus = 'pending'): PlanDetail {
  return {
    plan: {
      id: '4e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
      projectId: 'p1',
      planVersion: 1,
      activities: [],
      skipped: [],
      reason: 'r',
      createdAt: 't',
    },
    tasks: [{ taskId: 'task-scaffold', milestone: 1, title: '建立页面骨架', status: taskStatus }],
  }
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/projects/p1']}>
      <Routes>
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedPlan.mockResolvedValue(planDetail())
})

describe('详情页阶段验收', () => {
  it('点击测试验收：跑套件 → 提交 → 刷新任务状态为已完成', async () => {
    mockedRunSuite.mockResolvedValue({ totalFiles: 1, totalPassed: 2, totalFailed: 0, errorFiles: 0 })
    mockedEvaluate.mockResolvedValue({
      taskId: 'task-scaffold', status: 'done', passed: true,
      rubricVersion: 'suite-green-v1', evidenceConcepts: ['browser.dom'],
    })
    // 第一次 getPlan 返回 pending；验收后第二次返回 done
    mockedPlan
      .mockResolvedValueOnce(planDetail('pending'))
      .mockResolvedValueOnce(planDetail('done'))

    renderDetail()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '▶ 测试验收' }))

    await waitFor(() => expect(mockedEvaluate).toHaveBeenCalledWith('p1', 'task-scaffold', {
      totalFiles: 1, totalPassed: 2, totalFailed: 0, errorFiles: 0, traceId: 'trace-1',
    }))
    await waitFor(() => expect(screen.getByText('已完成')).toBeTruthy())
    expect(screen.queryByRole('button', { name: '▶ 测试验收' })).toBeNull() // done 后按钮消失
  })

  it('依赖未满足的 422 错误可见', async () => {
    mockedRunSuite.mockResolvedValue({ totalFiles: 1, totalPassed: 1, totalFailed: 0, errorFiles: 0 })
    const { ApiError } = await import('../api/client')
    mockedEvaluate.mockRejectedValue(new ApiError(422, '前置任务尚未完成：task-scaffold'))
    renderDetail()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '▶ 测试验收' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/前置任务尚未完成/)).toBeTruthy()
    expect(screen.getByText('待开始')).toBeTruthy() // 状态未变
  })

  it('已完成的任务不显示验收按钮', async () => {
    mockedPlan.mockResolvedValue(planDetail('done'))
    renderDetail()
    await screen.findByText('已完成')
    expect(screen.queryByRole('button', { name: '▶ 测试验收' })).toBeNull()
  })
})
