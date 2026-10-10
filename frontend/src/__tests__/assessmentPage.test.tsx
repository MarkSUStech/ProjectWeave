/** 诊断页流程测试：进入→作答→提交→结果（mock API）。 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssessmentPage from '../pages/AssessmentPage'
import type { AssessmentSession } from '../types/assessment'

vi.mock('../api/assessments', () => ({
  startAssessment: vi.fn(),
  submitAssessment: vi.fn(),
  getAssessment: vi.fn(),
  listProjectAssessments: vi.fn(),
}))
vi.mock('../api/concepts', () => ({
  listConcepts: vi.fn().mockResolvedValue({ items: [], domains: [] }),
}))
vi.mock('../api/projects', () => ({
  getProject: vi.fn().mockResolvedValue({
    id: 'p1', ownerId: 'dev-user', title: '诊断项目', description: '',
    mode: 'rebuild', status: 'draft', complexity: 'small',
    targetFeatures: [], nonGoals: [], stack: ['TypeScript'],
    milestones: [], acceptanceCriteria: [], specVersion: 1,
    createdAt: 't', updatedAt: 't',
  }),
}))

const { startAssessment, submitAssessment, listProjectAssessments } = await import('../api/assessments')
const mockedStart = vi.mocked(startAssessment)
const mockedSubmit = vi.mocked(submitAssessment)
const mockedList = vi.mocked(listProjectAssessments)

const inProgress: AssessmentSession = {
  id: 's1',
  projectId: 'p1',
  status: 'in-progress',
  items: [
    {
      itemId: 'q.a',
      conceptId: 'js.values-types',
      prompt: 'typeof null ?',
      options: ["'null'", "'object'", "'undefined'", 'TypeError'],
      difficulty: 1,
    },
    {
      itemId: 'q.b',
      conceptId: 'js.functions',
      prompt: '默认参数问题',
      options: ['A0', 'A1', 'A2', 'A3'],
      difficulty: 2,
    },
  ],
  results: null,
  createdAt: 't',
  completedAt: null,
}

const completed: AssessmentSession = {
  ...inProgress,
  status: 'completed',
  completedAt: 't2',
  results: {
    concepts: [
      { conceptId: 'js.values-types', label: 'likely-mastered', correctCount: 1, total: 1 },
      { conceptId: 'js.functions', label: 'likely-gap', correctCount: 0, total: 1 },
    ],
    questions: [
      { itemId: 'q.a', conceptId: 'js.values-types', correct: true, selectedOptionIndex: 1, correctOptionIndex: 1 },
      { itemId: 'q.b', conceptId: 'js.functions', correct: false, selectedOptionIndex: 0, correctOptionIndex: 2 },
    ],
  },
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:id/assessment" element={<AssessmentPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue([])
})

describe('AssessmentPage', () => {
  it('无历史时自动开始新诊断并进入作答', async () => {
    mockedStart.mockResolvedValue(inProgress)
    renderAt('/projects/p1/assessment')
    expect(await screen.findByText('typeof null ?')).toBeTruthy()
    expect(mockedStart).toHaveBeenCalledWith('p1')
  })

  it('未答完不允许提交；答完两题后提交成功进入结果视图', async () => {
    mockedStart.mockResolvedValue(inProgress)
    mockedSubmit.mockResolvedValue(completed)
    renderAt('/projects/p1/assessment')
    await screen.findByText('typeof null ?')

    const user = userEvent.setup()
    // 提交按钮在最后一题，先答第一题
    await user.click(screen.getByText("'object'", { selector: 'button *' }).closest('button')!)
    await user.click(screen.getByRole('button', { name: '下一题' }))
    expect(screen.getByText('默认参数问题')).toBeTruthy()
    // 第二题未作答 → 按钮提示未答完
    expect(screen.getByRole('button', { name: /还有 1 题未作答/ })).toBeTruthy()
    await user.click(screen.getByText('A2').closest('button')!)
    await user.click(screen.getByRole('button', { name: '提交诊断' }))

    expect(mockedSubmit).toHaveBeenCalledWith('s1', [
      { itemId: 'q.a', selectedOptionIndex: 1 },
      { itemId: 'q.b', selectedOptionIndex: 2 },
    ])
    expect(await screen.findByText('初步判断已掌握')).toBeTruthy()
    expect(screen.getByText('疑似薄弱')).toBeTruthy()
    expect(screen.getByText(/回答错误/)).toBeTruthy()
  })

  it('已有完成的历史时直接显示结果', async () => {
    mockedList.mockResolvedValue([
      { id: 's0', status: 'completed', createdAt: 't', completedAt: 't2', results: completed.results },
    ])
    const { getAssessment } = await import('../api/assessments')
    vi.mocked(getAssessment).mockResolvedValue(completed)
    renderAt('/projects/p1/assessment')
    expect(await screen.findByText('概念判断')).toBeTruthy()
    expect(mockedStart).not.toHaveBeenCalled()
  })

  it('初始化失败显示错误', async () => {
    mockedStart.mockRejectedValue(new Error('boom'))
    renderAt('/projects/p1/assessment')
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
  })
})
