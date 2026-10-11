/** AI Mentor 面板测试（mock tutor API；含工作台动作接线场景 A-E）。 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MentorPanel } from '../components/ide/MentorPanel'
import { ApiError } from '../api/client'
import type { TutorDecision } from '../types/tutor'
import { useIdeUiStore } from '../stores/ideUiStore'
import { useWorkspaceStore } from '../stores/workspaceStore'

vi.mock('../api/tutor', () => ({
  createTutorTurn: vi.fn(),
  listTutorDecisions: vi.fn(),
}))
vi.mock('../lib/eventTracker', () => ({ trackClientEvent: vi.fn() }))
vi.mock('../components/ide/CodeDiff', () => ({ default: ({ original, modified }: { original: string; modified: string }) => <div data-testid="proposal-diff">{original} → {modified}</div> }))

const { createTutorTurn, listTutorDecisions } = await import('../api/tutor')
const mockedTurn = vi.mocked(createTutorTurn)
const mockedList = vi.mocked(listTutorDecisions)

/** A2 应用回调桩（宿主守卫逻辑在 IdePage，此处仅验证接线与调用）。 */
const applyPatch = vi.fn().mockReturnValue({ applied: true })

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
  workspaceActions: [], toolCalls: [], agentRounds: 0,
  policyVersion: 'gate-v1',
  promptTokens: 800,
  completionTokens: 120,
  model: 'deepseek-chat',
  createdAt: '2026-10-10T12:00:00Z',
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  applyPatch.mockReturnValue({ applied: true })
  mockedList.mockResolvedValue([])
  // 工作台动作会触碰全局 store，测试间复位（场景 A/B 依赖干净初始态）
  useIdeUiStore.setState({ mode: 'coding', locked: false })
  useWorkspaceStore.setState({ notices: [], undoStack: [], pendingPatch: null })
})


describe('MentorPanel', () => {
  it('空历史显示引导文案；发送问题后追加 AI 回复带徽标', async () => {
    mockedTurn.mockResolvedValue(decision())
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
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
    expect(mockedTurn).toHaveBeenCalledWith('p1', '预览为什么不更新？', expect.objectContaining({ requestAnswerLevel: false }))
  })

  it('503 显示 AI 未配置状态', async () => {
    mockedTurn.mockRejectedValue(new ApiError(503, 'AI 未配置或不可用'))
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/问一个关于当前任务的问题/), 'q')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByText(/PW_AI_PROVIDER=deepseek/)).toBeTruthy()
    expect(screen.getByText(/AI 未配置（后端 \.env）/)).toBeTruthy()
  })

  it('失败显示错误且不吞掉', async () => {
    mockedTurn.mockRejectedValue(new ApiError(502, 'AI 调用失败'))
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/问一个关于当前任务的问题/), 'q')
    await user.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
  })

  it('历史决策直接渲染（含降级徽标）', async () => {
    mockedList.mockResolvedValue([decision({ outcome: 'degraded', outcomeReason: '非法 intent' })])
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
    expect(await screen.findByText('已降级')).toBeTruthy()
    expect(screen.getByText(/预览为什么不更新/)).toBeTruthy()
  })

  it('真实决策中的代码提案与当前草稿只读对比，不调用新的教学请求', async () => {
    mockedList.mockResolvedValue([decision({ workspaceActions: [{ kind: 'propose-patch', level: 'A2', reason: '已请求 H4', payload: { path: 'src/main.ts', content: 'const answer = 2' } }] })])
    render(<MentorPanel projectId="p1" currentFile={{ path: 'src/main.ts', content: 'const answer = 1' }} onApplyPatch={applyPatch} />)
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看代码提案差异' }))
    expect(screen.getByRole('dialog', { name: 'AI 代码提案 · src/main.ts' })).toBeTruthy()
    expect((await screen.findByTestId('proposal-diff')).textContent).toBe('const answer = 1 → const answer = 2')
    expect(mockedTurn).not.toHaveBeenCalled()
  })
})

describe('MentorPanel 工作台动作接线（验收场景 A-E）', () => {
  const layoutAction = {
    kind: 'switch-layout', level: 'A1', reason: '看变量变化',
    payload: { mode: 'visual-learning' },
  } as const
  const patchAction = {
    kind: 'propose-patch', level: 'A2', reason: '已请求 H4',
    payload: { path: 'src/main.ts', content: 'const v2 = 2', description: '修正实现' },
  } as const

  async function sendQuestion(question = '帮我排查') {
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/问一个关于当前任务的问题/), question)
    await user.click(screen.getByRole('button', { name: '发送' }))
  }

  it('场景 A：未锁定时 AI 切换布局生效且可撤销', async () => {
    mockedTurn.mockResolvedValue(decision({ workspaceActions: [layoutAction] }))
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
    await sendQuestion()
    await waitFor(() => expect(useIdeUiStore.getState().mode).toBe('visual-learning'))
    expect(useWorkspaceStore.getState().undoStack).toHaveLength(1)
    const { undoLastLayoutChange } = await import('../lib/workspace/executor')
    undoLastLayoutChange('p1')
    expect(useIdeUiStore.getState().mode).toBe('coding')
  })

  it('场景 B：锁定后 AI 切换建议被拒绝，布局保持不变', async () => {
    useIdeUiStore.setState({ locked: true })
    mockedTurn.mockResolvedValue(decision({ workspaceActions: [layoutAction] }))
    render(<MentorPanel projectId="p1" onApplyPatch={applyPatch} />)
    await sendQuestion()
    await waitFor(() => expect(useWorkspaceStore.getState().notices).toHaveLength(1))
    expect(useIdeUiStore.getState().mode).toBe('coding')
    expect(useWorkspaceStore.getState().notices[0].tone).toBe('warn')
    expect(useWorkspaceStore.getState().undoStack).toHaveLength(0)
  })

  it('场景 C/D：补丁先入队列，用户在差异弹窗确认后才调用 applyPatch', async () => {
    mockedTurn.mockResolvedValue(decision({ workspaceActions: [patchAction] }))
    render(
      <MentorPanel
        projectId="p1"
        currentFile={{ path: 'src/main.ts', content: 'const v1 = 1' }}
        onApplyPatch={applyPatch}
      />,
    )
    await sendQuestion()
    await waitFor(() => expect(useWorkspaceStore.getState().pendingPatch?.kind).toBe('propose-patch'))
    expect(applyPatch).not.toHaveBeenCalled() // 场景 C：未确认源码不变

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看代码提案差异' }))
    await userEvent.setup().click(screen.getByRole('button', { name: '应用到编辑器草稿' }))
    await waitFor(() => expect(applyPatch).toHaveBeenCalledWith('src/main.ts', 'const v2 = 2'))
    expect(useWorkspaceStore.getState().pendingPatch).toBeNull()
  })

  it('拒绝按钮清空队列且不应用', async () => {
    mockedTurn.mockResolvedValue(decision({ workspaceActions: [patchAction] }))
    render(
      <MentorPanel
        projectId="p1"
        currentFile={{ path: 'src/main.ts', content: 'x' }}
        onApplyPatch={applyPatch}
      />,
    )
    await sendQuestion()
    await waitFor(() => expect(useWorkspaceStore.getState().pendingPatch).not.toBeNull())
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看代码提案差异' }))
    await userEvent.setup().click(screen.getByRole('button', { name: '拒绝' }))
    expect(applyPatch).not.toHaveBeenCalled()
    expect(useWorkspaceStore.getState().pendingPatch).toBeNull()
  })
})


// ---------------------------------------------------------------- P6 Agent 工具轨迹

function traceDecision() {
  return {
    id: '9e2d6f6e-1b1f-4c0f-9b8a-2f2f5c6a7b8e',
    projectId: 'p1', question: '为什么崩溃', trigger: 'user',
    intent: 'hint', hintLevel: 2, message: '提示', targetConcepts: [],
    explanation: '', confidence: 0.8, outcome: 'accepted', outcomeReason: '',
    workspaceActions: [],
    toolCalls: [
      { tool: 'read_project_file', args: { path: 'src/main.cpp' }, ok: true, round: 1, durationMs: 12, summary: '{}', error: null },
      { tool: 'get_recent_diagnostics', args: {}, ok: true, round: 2, durationMs: 8, summary: '{}', error: null },
      { tool: 'exec_shell', args: {}, ok: false, round: 2, durationMs: 1, summary: '', error: '未知工具：exec_shell（白名单外）' },
    ],
    agentRounds: 3, policyVersion: 'gate-v1', promptTokens: 100, completionTokens: 50,
    model: 'deepseek-chat', createdAt: '2026-10-11T00:00:00Z',
  } as unknown as import('../types/tutor').TutorDecision
}

describe('Agent 工具调用轨迹（P6）', () => {
  it('渲染真实后端轨迹：成功/失败与文件参数', async () => {
    const { DecisionBubble } = await import('../components/ide/MentorPanel')
    render(
      <DecisionBubble
        decision={traceDecision()}
        projectId="p1"
        onApplyPatch={() => ({ ok: true }) as never}
      />,
    )
    const header = screen.getByText(/Agent 探索（3 次工具调用 · 3 轮）/)
    const trace = header.parentElement?.textContent ?? ''
    expect(trace).toContain('读取')
    expect(trace).toContain('src/main.cpp')
    expect(trace).toContain('获取最近的编译/运行错误')
    expect(trace).toContain('未知工具：exec_shell')
  })
})
