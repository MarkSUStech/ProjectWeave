/** AI Mentor 面板测试（mock tutor API）。 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MentorPanel } from '../components/ide/MentorPanel'
import { ApiError } from '../api/client'
import type { TutorDecision } from '../types/tutor'

vi.mock('../api/tutor', () => ({
  createTutorTurn: vi.fn(),
  listTutorDecisions: vi.fn(),
}))

const { createTutorTurn, listTutorDecisions } = await import('../api/tutor')
const mockedTurn = vi.mocked(createTutorTurn)
const mockedList = vi.mocked(listTutorDecisions)

const decision = (overrides: Partial<TutorDecision> = {}): TutorDecision => ({
  id: '5e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8d',
  projectId: 'p1',
  question: '预览为什么不更新？',
  trigger: 'user',
  intent: 'hint',
  hintLevel: 1,
  message: '想一想输入事件触发后，是谁负责把新内容写进预览区域？',
  targetConcepts: ['js.callbacks-events'],
  explanation: '用户卡在事件流',
  confidence: 0.7,
  outcome: 'accepted',
  outcomeReason: '',
  policyVersion: 'gate-v1',
  promptTokens: 800,
  completionTokens: 120,
  model: 'deepseek-chat',
  createdAt: '2026-10-10T12:00:00Z',
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue([])
})

describe('MentorPanel', () => {
  it('空历史显示引导文案；发送问题后追加 AI 回复带徽标', async () => {
    mockedTurn.mockResolvedValue(decision())
    render(<MentorPanel projectId="p1" />)
    expect(await screen.findByText(/启发式提问/)).toBeTruthy()

    const user = userEvent.setup()
    const input = screen.getByPlaceholderText(/问一个关于当前任务的问题/)
    await user.type(input, '预览为什么不更新？')
    await user.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => expect(screen.getByText(/是谁负责把新内容写进预览/)).toBeTruthy())
    expect(screen.getByText('提示')).toBeTruthy()
    expect(screen.getByText('H1')).toBeTruthy()
    expect(screen.getByText('js.callbacks-events')).toBeTruthy()
    expect(screen.getByText(/920 tokens/)).toBeTruthy()
    expect(mockedTurn).toHaveBeenCalledWith('p1', '预览为什么不更新？', { requestAnswerLevel: false })
  })

  it('503 显示 AI 未配置状态', async () => {
    mockedTurn.mockRejectedValue(new ApiError(503, 'AI 未配置或不可用'))
    render(<MentorPanel projectId="p1" />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/问一个关于当前任务的问题/), 'q')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByText(/PW_AI_PROVIDER=deepseek/)).toBeTruthy()
    expect(screen.getByText(/AI 未配置（后端 \.env）/)).toBeTruthy()
  })

  it('失败显示错误且不吞掉', async () => {
    mockedTurn.mockRejectedValue(new ApiError(502, 'AI 调用失败'))
    render(<MentorPanel projectId="p1" />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/问一个关于当前任务的问题/), 'q')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
  })

  it('历史决策直接渲染（含降级徽标）', async () => {
    mockedList.mockResolvedValue([decision({ outcome: 'degraded', outcomeReason: '非法 intent' })])
    render(<MentorPanel projectId="p1" />)
    expect(await screen.findByText('已降级')).toBeTruthy()
    expect(screen.getByText(/预览为什么不更新/)).toBeTruthy()
  })
})
